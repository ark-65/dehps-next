"""Compare evidence before selecting; distinguish validated Qwen from learned-value fallback."""

import random

from psycopg.types.json import Jsonb

from .domain import digest
from .errors import DomainError
from .research_agent import infer
from .research_memory import recall
from .research_policy import train_policy
from .research_review import candidate_pool, changes, counts, cross_round_feedback
from .research_selection_evidence import SEMANTIC_FAILURES, mechanism_progress, observe_positions


def selection_status(db):
    state = db.rows("SELECT * FROM qwen_selection_state WHERE id=1")
    rows = db.rows("SELECT source,payload FROM qwen_selection_audits ORDER BY id DESC LIMIT 100")
    positions = [p for r in rows if r["source"] == "QWEN_COMPARATIVE" for p in r["payload"]["positions"]][
        :100
    ]
    effects = db.rows("""SELECT study_id,payload FROM research_review_results
        WHERE payload->>'kind'='SELECTION_EFFECT_24_V4' ORDER BY created_at DESC LIMIT 3""")
    return {
        "state": state[0] if state else None,
        "sources": db.rows("SELECT source,count(*) AS n FROM qwen_selection_audits GROUP BY source"),
        "recent_qwen_slots": len(positions),
        "active_inference": db.rows("""SELECT id,campaign_id,model,created_at,
            metrics->'wall_seconds' AS observed_wall_seconds,
            metrics->'stream_bytes_observed' AS output_bytes_observed,
            metrics->'stream_chunks_observed' AS chunks_not_tokens,
            metrics->>'count_scope' AS receipt_scope
            FROM research_model_calls WHERE state='RESERVED' ORDER BY id DESC LIMIT 1"""),
        "first_position_fraction": sum(p["position"] == 0 for p in positions) / len(positions)
        if positions
        else None,
        "mechanism_studies": db.rows("""SELECT study_id,payload FROM research_review_results
            WHERE payload->>'kind'='MECHANISM_PROFILE_V4' ORDER BY created_at DESC LIMIT 6"""),
        "mechanism_progress": mechanism_progress(db),
        "effect_studies": effects,
        "feedback_effectiveness": (
            "DEVELOPMENT_COMPARISON_BENEFIT"
            if effects[0]["payload"]["comparison"]["feedback_better_in_this_study"]
            else "NO_DEVELOPMENT_BENEFIT_DEMONSTRATED"
        )
        if effects
        else "NOT_ESTABLISHED",
        "evidence_scope": "HISTORICAL_DEVELOPMENT;MECHANISM_PASS_IS_NOT_PREDICTIVE_PROOF",
    }


def make_context(
    parent, business, offered, memory, *, count=2, feedback=True, layout_seed=1729, id_seed=1729
):
    candidates = {"r" + digest([id_seed, spec])[:7]: spec for spec in offered[:6]}
    if len(candidates) != min(len(offered), 6):
        raise DomainError("CANDIDATE_ID_COLLISION", "Distinct recipes require distinct opaque IDs")
    ids = list(candidates)
    groups = {"repair": ids[:3], "explore": ids[3:]} if count == 2 else {"choose": ids}
    for name, group in groups.items():
        if len(group) < 3:
            raise DomainError("INSUFFICIENT_REAL_CHOICES", "Every group retains at least three recipes")
        random.Random(digest([layout_seed, name])).shuffle(group)
    evidence = (
        memory["evidence"]
        if feedback and memory["evidence"]
        else [{"key": "parent", "spec": parent, "hits": counts(business), "verdict": "ACCEPTED_PARENT"}]
    )
    context = {
        "task": "Assess EVERY candidate using the supplied evidence, rank every group, then select its best ID. "
        "IDs and input positions are arbitrary. Larger known_utility is better when provided for completed "
        "historical trials. For untried candidates outcomes are UNKNOWN: use failures as analogies, never invent scores. "
        "Emit assessments first, rankings second, selection last. "
        'Evidence contains ONLY exact key strings, e.g. ["f0"], not descriptions. '
        "Copy known_utility from an exact observed recipe, otherwise null. "
        "Each assessment must compare utility or risk in at most twelve words, not repeat a candidate name.",
        "groups": groups,
        "candidates": [
            {
                "id": key,
                "spec": candidates[key],
                "changes": changes(parent, candidates[key]),
                "observed_evidence_keys": [e["key"] for e in evidence if e["spec"] == candidates[key]],
                "known_utility": next(
                    (e.get("known_utility") for e in evidence if e["spec"] == candidates[key]), None
                ),
            }
            for group in groups.values()
            for key in group
        ],
        "parent": {"spec": parent, "hits100_50_10": counts(business)},
        "hits_definition": "red5+Top100,blueTop1 counts for100/50/10;all nested in100 labels",
        "promotion": "one100-rate improves;both nondecreasing in100/50/10;no50percent gate",
        "evidence": [
            {k: e[k] for k in ("key", "spec", "hits", "verdict", "known_utility") if k in e} for e in evidence
        ],
    }
    if feedback:
        context["family_feedback"] = [
            {k: r[k] for k in ("method", "n", "red_risk", "blue_risk", "improved")}
            for r in memory.get("families", [])
        ]
        context["comparable_trials"] = memory["trials"]
    text = {"type": "string"}
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["assessments", "rankings", "selection"],
        "properties": {
            "assessments": {
                "type": "array",
                "minItems": len(ids),
                "maxItems": len(ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["candidate", "evidence", "known_utility", "assessment"],
                    "properties": {
                        "candidate": text,
                        "evidence": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 4,
                            "items": {"type": "string", "enum": [e["key"] for e in evidence]},
                        },
                        "known_utility": {"type": ["number", "null"]},
                        "assessment": {"type": "string", "minLength": 8, "maxLength": 96},
                    },
                },
            },
            "rankings": {
                "type": "object",
                "additionalProperties": False,
                "required": list(groups),
                "properties": {
                    g: {"type": "array", "minItems": len(v), "maxItems": len(v), "items": text}
                    for g, v in groups.items()
                },
            },
            "selection": {
                "type": "object",
                "additionalProperties": False,
                "required": list(groups),
                "properties": {g: text for g in groups},
            },
        },
    }
    return context, schema, candidates, groups, evidence


def select(
    db,
    artifacts,
    campaign,
    job,
    pulse,
    parent,
    business,
    offered,
    memory,
    profile,
    *,
    count=2,
    feedback=True,
    layout_seed=1729,
    id_seed=1729,
):
    context, schema, candidates, groups, evidence = make_context(
        parent,
        business,
        offered,
        memory,
        count=count,
        feedback=feedback,
        layout_seed=layout_seed,
        id_seed=id_seed,
    )
    reply, receipt = infer(
        db,
        artifacts,
        campaign,
        job,
        "CANDIDATE_SELECTION_V4_" + ("FEEDBACK" if feedback else "NO_FEEDBACK"),
        context,
        schema,
        pulse,
        profile=profile,
    )
    observation = observe_positions(context, reply)
    try:
        if list(reply) != ["assessments", "rankings", "selection"]:
            raise ValueError("Candidate assessment must precede ranking and selection")
        assessments = {r["candidate"]: r for r in reply["assessments"]}
        if len(reply["assessments"]) != len(candidates) or set(assessments) != set(candidates):
            raise ValueError("Assess every distinct candidate exactly once")
        supplied = {e["key"]: e for e in evidence}
        for key, record in assessments.items():
            cited = record["evidence"]
            if not cited or not set(cited) <= set(supplied) or not 8 <= len(record["assessment"]) <= 96:
                raise ValueError("Ground each comparison in supplied evidence")
            observed = [e.get("known_utility") for e in evidence if e["spec"] == candidates[key]]
            expected = observed[0] if observed else None
            if record["known_utility"] != expected:
                raise ValueError("Observed utility must match the actual exact recipe; unknown stays null")
            if record["assessment"].strip().lower() in ("candidate " + key, key):
                raise ValueError("A candidate label is not a comparison")
            exact = {e["key"] for e in evidence if e["spec"] == candidates[key]}
            if exact and not exact.intersection(cited):
                raise ValueError("An already observed exact recipe must cite its actual record")
        if set(reply["rankings"]) != set(groups) or set(reply["selection"]) != set(groups):
            raise ValueError("Rank and select every actual group")
        picks, positions = [], []
        for group, ids in groups.items():
            ranking = reply["rankings"][group]
            if len(ranking) != len(ids) or set(ranking) != set(ids):
                raise ValueError("Group ranking must contain its alternatives exactly once")
            key = reply["selection"][group]
            if key != ranking[0]:
                raise ValueError("Selection must follow the comparative ranking")
            comparison = assessments[key]
            delta = changes(parent, candidates[key])
            if not delta:
                raise ValueError("A new direction must change its parent")
            picks.append(
                {
                    "candidate_id": key,
                    "spec": candidates[key],
                    "parameter_changes": delta,
                    "cited_feedback": supplied[comparison["evidence"][0]],
                    "selection": {"group": group, "candidate": key},
                    "hypothesis": f"{comparison['assessment']};exact changes:{delta};unvalidated",
                    "falsification": "Unchanged paired100/50/10;never substitute Qwen claims for recorded outcomes",
                }
            )
            positions.append(
                {
                    "group": group,
                    "position": ids.index(key),
                    "options": len(ids),
                    "recipe": digest(candidates[key]),
                }
            )
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        with db.pool.connection() as c:
            c.execute(
                "UPDATE research_model_calls SET state='FAILED',metrics=metrics||%s WHERE id=%s",
                (Jsonb({"failure_code": "INVALID_COMPARATIVE_SELECTION"}), receipt["call_id"]),
            )
        failure = DomainError("INVALID_COMPARATIVE_SELECTION", str(exc))
        failure.position_observation = observation
        raise failure from exc
    return (
        picks,
        receipt,
        {
            "context": context,
            "reply": reply,
            "schema": schema,
            "positions": positions,
            "candidate_identities": {k: digest(v) for k, v in candidates.items()},
            "minimum_group_options": min(map(len, groups.values())),
            "layout_seed": layout_seed,
            "id_seed": id_seed,
            "input_digest": digest(context),
            "with_feedback": feedback,
            "profile_id": digest(profile),
        },
    )


def mechanism_metrics(db, study, profile):
    """Recompute activation gates from the immutable trials, not a claimed pass flag."""
    pairs = {
        r["pair"]: r
        for r in db.rows("SELECT pair,basis,sha256 FROM research_review_pairs WHERE study_id=%s", (study,))
    }
    rows = db.rows("SELECT pair,arm,payload FROM research_review_selections WHERE study_id=%s", (study,))
    variants, seeds = ("base", "display", "identifier"), (1729, 43107)
    expected = {
        (i, f"{arm}:{variant}:{seed}")
        for i in range(12)
        for arm in ("feedback", "no_feedback")
        for variant in variants
        for seed in seeds
    }
    if set(pairs) != set(range(12)) or {(r["pair"], r["arm"]) for r in rows} != expected:
        raise DomainError("MECHANISM_NOT_VALIDATED", "Require all144 actual frozen mechanism requests")
    for r in pairs.values():
        b = r["basis"]
        if digest(b) != r["sha256"] or b["oracle_spec_digest"] not in b["utilities"]:
            raise DomainError("MECHANISM_NOT_VALIDATED", "Frozen case identity mismatch")
        best = max(b["utilities"].values())
        if b["utilities"][b["oracle_spec_digest"]] != best or list(b["utilities"].values()).count(best) != 1:
            raise DomainError("MECHANISM_NOT_VALIDATED", "Require a unique recorded best recipe")
    outcomes = {(r["pair"], r["arm"]): r["payload"] for r in rows}
    feedback = [r for r in rows if r["arm"].startswith("feedback:")]
    control = [r for r in rows if r["arm"].startswith("no_feedback:")]
    for r in rows:
        p = r["payload"]
        if not p["valid"]:
            if p.get("error") not in SEMANTIC_FAILURES:
                raise DomainError(
                    "MECHANISM_NOT_VALIDATED",
                    "An infrastructure interruption is not a performed semantic choice",
                )
            continue
        receipt = p["receipt"]
        seed = int(r["arm"].split(":")[-1])
        actual_profile = {**profile, "options": {**profile["options"], "seed": seed}}
        m = receipt["metrics"]
        gpu = m.get("offload") or {}
        if (
            receipt["model_digest"] != profile["model_digest"]
            or m.get("selection_profile") != actual_profile
            or not m.get("prompt_eval_count")
            or not m.get("eval_count")
            or not gpu.get("size")
            or gpu.get("size_vram", 0) < gpu["size"]
            or gpu.get("context_length") != profile["options"]["num_ctx"]
            or digest(p["proof"]["context"]) != p["proof"]["input_digest"]
        ):
            raise DomainError(
                "MECHANISM_NOT_VALIDATED", "Require pinned configuration, real receipts and full GPU"
            )

    def accuracy(records):
        return (
            sum(
                r["payload"]["valid"]
                and r["payload"].get("selected") == pairs[r["pair"]]["basis"]["oracle_spec_digest"]
                for r in records
            )
            / 72
        )

    same = 0
    for i in range(12):
        for seed in seeds:
            base = outcomes[i, f"feedback:base:{seed}"]
            for variant in variants[1:]:
                other = outcomes[i, f"feedback:{variant}:{seed}"]
                same += bool(base["valid"] and other["valid"] and base["selected"] == other["selected"])
    valid = [r["payload"] for r in feedback if r["payload"]["valid"]]
    return {
        "semantic_accuracy": accuracy(feedback),
        "accuracy_feedback_lift": accuracy(feedback) - accuracy(control),
        "recipe_stability": same / 48,
        "first_position_fraction": sum(p["position"] == 0 for p in valid) / len(valid) if valid else 1.0,
    }


def activate(db, profile, study):
    result = db.rows("SELECT payload FROM research_review_results WHERE study_id=%s", (study,))
    if not result:
        raise DomainError("MECHANISM_NOT_VALIDATED", "Freeze and complete the mechanism study first")
    r = result[0]["payload"]
    identity = digest(profile)
    actual = mechanism_metrics(db, study, profile)
    if (
        r.get("profile_id") != identity
        or profile.get("selector_contract") != "comparative-v4.4"
        or not r.get("passed")
        or r.get("executed_feedback") != 72
        or r.get("executed_no_feedback") != 72
        or r.get("not_run") != 0
        or any(abs(actual[k] - r[k]) > 1e-12 for k in actual)
        or r["semantic_accuracy"] < 0.9
        or r["recipe_stability"] < 0.8
        or r["first_position_fraction"] > 0.5
        or r["accuracy_feedback_lift"] < 0.2
    ):
        raise DomainError("MECHANISM_NOT_VALIDATED", "Do not activate a failed or different model profile")
    with db.pool.connection() as c, c.transaction():
        c.execute("SELECT pg_advisory_xact_lock(740134)")
        if c.execute("""SELECT 1 FROM jobs j JOIN research_nodes n ON n.id=j.research_node_id
            JOIN research_campaigns r ON r.id=n.campaign_id WHERE r.config->>'proposal_policy'='candidates-v4'
            AND j.state IN ('READY','RUNNING') LIMIT 1""").fetchone():
            raise DomainError(
                "ACTIVE_SELECTION_PROFILE", "Finish the frozen selection campaign before switching models"
            )
        c.execute(
            "INSERT INTO qwen_selection_profiles(id,config,mechanism_study) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
            (identity, Jsonb(profile), study),
        )
        c.execute(
            "UPDATE qwen_selection_state SET profile_id=%s,reason=NULL,retry_after=NULL,updated_at=now() WHERE id=1",
            (identity,),
        )
    return identity


def propose_batch_v4(controller, campaign, nodes, count, job, pulse):
    db, a = controller.db, controller.artifacts
    parent = next(n for n in nodes if n["id"] == campaign["selected_node"])
    value, policy = train_policy(db, a, campaign, job)
    offered, pool_size = candidate_pool(db, campaign, parent, value, count)
    memory = cross_round_feedback(db, campaign, parent)
    head = recall(db, campaign, reason="COMPARATIVE_SELECTION")
    identity = campaign["config"].get("selection_profile_id")
    profiles = (
        db.rows("SELECT config FROM qwen_selection_profiles WHERE id=%s", (identity,)) if identity else []
    )
    state = db.rows(
        "SELECT *,retry_after IS NOT NULL AND retry_after<=now() AS retry_due FROM qwen_selection_state WHERE id=1"
    )[0]
    reason = state["reason"] if state["reason"] and not state["retry_due"] else None
    reason = reason or ("MECHANISM_NOT_VALIDATED" if not profiles else None)
    receipts = []
    proof = None
    picks = []
    attempted_context = None
    attempted_schema = None
    failed_call = None
    if not reason:
        try:
            layout = int(digest([parent["id"], offered])[:8], 16)
            attempted_context, attempted_schema, _, _, _ = make_context(
                parent["spec"],
                parent["evaluation"]["business"],
                offered,
                memory,
                count=count,
                layout_seed=layout,
                id_seed=layout ^ 0x85EBCA6B,
            )
            picks, receipt, proof = select(
                db,
                a,
                campaign,
                job,
                pulse,
                parent["spec"],
                parent["evaluation"]["business"],
                offered,
                memory,
                profiles[0]["config"],
                count=count,
                layout_seed=layout,
                id_seed=layout ^ 0x85EBCA6B,
            )
            receipts = [receipt]
            prior = db.rows(
                "SELECT payload FROM qwen_selection_audits WHERE source='QWEN_COMPARATIVE' AND payload->>'profile_id'=%s ORDER BY id DESC LIMIT 100",
                (identity,),
            )
            positions = proof["positions"] + [p for r in prior for p in r["payload"]["positions"]]
            if len(positions) >= 100 and sum(p["position"] == 0 for p in positions[:100]) >= 90:
                raise DomainError(
                    "QWEN_POSITION_BIAS", "At least90 of100 real choices followed the first position"
                )
        except DomainError as exc:
            if exc.code.startswith("YIELD_") or exc.code in ("LEASE_LOST", "INTERRUPTED"):
                raise
            reason = exc.code
            attempted = db.rows(
                """SELECT id,state,metrics FROM research_model_calls
                WHERE job_id=%s AND attempt_id=%s AND stage LIKE 'CANDIDATE_SELECTION_V4_%%'
                ORDER BY id DESC LIMIT 1""",
                (job["id"], job["token"]),
            )
            failed_call = attempted[0] if attempted else None
            with db.pool.connection() as c, c.transaction():
                db.fence(c, job)
                c.execute(
                    "UPDATE qwen_selection_state SET reason=%s,retry_after=CASE WHEN %s IN ('QWEN_POSITION_BIAS','INVALID_COMPARATIVE_SELECTION','INVALID_LOCAL_REPLY','LOCAL_MODEL_TRUNCATED','LOCAL_MODEL_DIGEST_MISMATCH','LOCAL_MODEL_CONTEXT_MISMATCH','LOCAL_MODEL_REPETITION') THEN NULL ELSE now()+interval '60 seconds' END,updated_at=now() WHERE id=1",
                    (reason, reason),
                )
            picks = []
    if reason:
        rejected = proof
        trained = policy["examples"] > 0
        context, _, candidates, groups, evidence = make_context(
            parent["spec"], parent["evaluation"]["business"], offered, memory, count=count
        )
        for group, ids in groups.items():
            key = max(
                ids,
                key=lambda k: (
                    value(candidates[k], parent["evaluation"]["summary"])
                    if trained
                    else int(digest([parent["id"], candidates[k]])[:12], 16),
                    digest(candidates[k]),
                ),
            )
            picks.append(
                {
                    "candidate_id": key,
                    "spec": candidates[key],
                    "parameter_changes": changes(parent["spec"], candidates[key]),
                    "selection": {"group": group, "candidate": key},
                    "cited_feedback": evidence[0],
                    "hypothesis": (
                        "Feedback-trained value network selected this untried recipe;Qwen not accepted: "
                        if trained
                        else "No comparable feedback yet;reproducible cold-start exploration;Qwen not accepted: "
                    )
                    + reason,
                    "falsification": "Unchanged paired100/50/10;not a successful Qwen selection",
                }
            )
        proof = {
            "positions": [
                {
                    "group": g,
                    "position": ids.index(
                        next(p["candidate_id"] for p in picks if p["selection"]["group"] == g)
                    ),
                    "options": len(ids),
                }
                for g, ids in groups.items()
            ],
            "context": context,
            "minimum_group_options": min(map(len, groups.values())),
            "input_digest": digest(context),
            "profile_id": identity,
            "reason": reason,
            "value_model_trained": trained,
            "rejected_qwen": rejected,
            "attempted_qwen_context": attempted_context,
            "attempted_qwen_schema": attempted_schema,
            "failed_qwen_call": failed_call,
        }
    source = (
        ("FEEDBACK_VALUE_FALLBACK" if trained else "COLD_START_EXPLORATION") if reason else "QWEN_COMPARATIVE"
    )
    basis = {
        "parent_id": parent["id"],
        "parent_anchor": campaign["selected_anchor"]["sha256"],
        "dataset_id": campaign["dataset_id"],
        "protocol_digest": campaign["protocol"]["digest"],
        "code_digest": campaign["config"]["code_digest"],
        "numeric_digest": campaign["config"]["numeric_digest"],
        "numeric_threads": campaign["config"]["numeric_threads"],
        "selection_profile_id": identity,
        "feedback_nodes": [e["node"] for e in memory["evidence"]],
        "offered_digest": digest(offered),
        "memory": head,
    }
    with db.pool.connection() as c, c.transaction():
        db.fence(c, job)
        c.execute(
            "INSERT INTO qwen_selection_audits(campaign_id,call_id,source,payload) VALUES(%s,%s,%s,%s)",
            (
                campaign["id"],
                receipts[0]["call_id"] if receipts else failed_call["id"] if failed_call else None,
                source,
                Jsonb(proof),
            ),
        )
    for pick in picks:
        pick.update(
            source=source,
            pipeline_basis=basis,
            inference=receipts,
            direction_value_model=policy,
            offered_count=len(offered),
            novel_pool_count=pool_size,
            review_evidence={
                "input_digest": proof["input_digest"],
                "selection": pick["selection"],
                "minimum_group_options": proof["minimum_group_options"],
                "through_seq": memory["through_seq"],
                "family_summary": memory["families"],
                "selection_source": source,
                "profile_id": identity,
                "fallback_reason": reason,
            },
        )
    return basis, picks
