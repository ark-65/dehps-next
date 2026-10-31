"""Novel candidate selection and a two-node, parent-fenced research pipeline."""

from psycopg.types.json import Jsonb

from .domain import digest
from .errors import DomainError
from .release import numeric_identity
from .research_agent import infer
from .research_math import run_tool
from .research_memory import feedback_contract, recall, untried_specs
from .research_policy import train_policy
from .research_search import novel_specs


def pending(nodes):
    return [n for n in nodes if n["evaluation"] is None and n["status"] != "STALE_PARENT"]


def same_basis(campaign, basis):
    return (
        campaign["selected_node"] == basis["parent_id"]
        and campaign["selected_anchor"]
        and campaign["selected_anchor"]["sha256"] == basis["parent_anchor"]
        and campaign["dataset_id"] == basis["dataset_id"]
        and campaign["protocol"]["digest"] == basis["protocol_digest"]
        and campaign["config"]["code_digest"] == basis["code_digest"]
        and campaign["config"]["numeric_digest"] == basis["numeric_digest"]
        and campaign["config"]["numeric_threads"] == basis["numeric_threads"]
    )


def feedback(db, campaign, nodes, selected):
    stored = db.rows(
        """SELECT node_id,spec,payload-'period_outcomes'-'origin_provenance' AS payload FROM research_memory_events WHERE contract=%s
        AND kind='EVALUATION' AND parent_id IS NOT NULL
        AND payload->>'campaign'!=%s ORDER BY seq DESC LIMIT 5""",
        (feedback_contract(campaign), campaign["id"]),
    )
    earlier = [
        {
            "id": r["node_id"],
            "spec": r["spec"],
            "path": r["payload"]["path"],
            "decision": r["payload"]["decision"],
            "evaluation": {"summary": r["payload"]["summary"], "business": r["payload"]["business"]},
        }
        for r in stored
    ]
    current = sorted(
        [n for n in nodes if n["evaluation"] and n["parent_id"]],
        key=lambda n: (n["completed_at"], n["id"]),
        reverse=True,
    )
    chosen = [selected]
    for n in current + earlier:
        if n["id"] not in {x["id"] for x in chosen}:
            chosen.append(n)
        if len(chosen) == 6:
            break
    records = []
    for i, n in enumerate(chosen):
        decision, evaluation = n["decision"], n["evaluation"]
        constraint = (
            "RED_DEGRADATION"
            if decision.get("red_brier_delta", 0) > campaign["protocol"]["red_brier_tolerance"]
            else "BLUE_REGRESSION"
            if decision["verdict"] == "PRUNE_REGRESSION"
            else "UNCERTAINTY"
            if decision["verdict"] == "INCONCLUSIVE"
            else "ACCEPTED_PARENT"
        )
        records.append(
            {
                "key": f"e{i}:{decision['verdict']}:{constraint}",
                "node": n["id"],
                "path": n["path"],
                "spec": n["spec"],
                "verdict": decision["verdict"],
                "constraint": constraint,
                "recent100_delta": decision.get("recent_delta"),
                "tail10_delta": decision.get("recent10_delta"),
                "random_delta": decision.get("random_historical_delta"),
                "red_delta": decision.get("red_brier_delta"),
                "paired_interval95": decision.get("paired_development_interval95"),
                "blue_loss": evaluation["summary"]["blue_log_loss"],
                "red_brier": evaluation["summary"]["red_brier"],
            }
        )
        if evaluation.get("business"):
            record = records[-1]
            record["hit_windows"] = {
                k: {"n": v["n"], "red5": v["red5_periods"], "blue": v["blue_hits"]}
                for k, v in evaluation["business"]["windows"].items()
            }
            record["paired_hit_deltas"] = decision.get("business", {}).get("paired_windows")
            record["constraint"] = (
                "PAIRED_HIT_REGRESSION"
                if decision["verdict"] == "PRUNE_REGRESSION"
                else "HIT_RATE_UNCERTAINTY"
                if decision["verdict"] == "INCONCLUSIVE"
                else "OBSERVED_HIT_BASELINE_OR_PROGRESS"
            )
            record["key"] = f"e{i}:{decision['verdict']}:{record['constraint']}"
            for key in ("recent100_delta", "tail10_delta", "random_delta", "red_delta", "paired_interval95"):
                record.pop(key)
    return records


def propose_batch(controller, campaign, nodes, count, job, pulse):
    db, artifacts = controller.db, controller.artifacts
    selected = next(n for n in nodes if n["id"] == campaign["selected_node"])
    topic = campaign["config"].get("topic") or {"methods": ["fft", "ridge", "newton"]}
    specs = novel_specs(db, campaign["dataset_id"], campaign["config"]["code_digest"], topic)
    if not specs:
        raise DomainError("SEARCH_SPACE_EXHAUSTED", "No untried recipe remains in the registered curriculum")
    value, policy = train_policy(db, artifacts, campaign, job)
    pulse()
    ranked = sorted(specs, key=lambda s: (-value(s, selected["evaluation"]["summary"]), digest(s)))
    # Interleave distinct method/window/history/width groups, then fill by learned score.
    offered, groups = [], set()
    for spec in ranked:
        group = (spec["method"], spec["window"], spec["train_history"], spec["hidden"])
        if group not in groups:
            offered.append(spec)
            groups.add(group)
        if len(offered) == 12:
            break
    for spec in ranked:
        if len(offered) == 12:
            break
        if spec not in offered:
            offered.append(spec)
    count = min(count, len(offered))
    candidates = {
        f"c{i}": {"spec": s, "estimated_reward": round(value(s, selected["evaluation"]["summary"]), 5)}
        for i, s in enumerate(offered)
    }
    ids = list(candidates)
    split = max(1, len(ids) // 2)
    slots = {"primary": ids if count == 1 else ids[:split]}
    if count == 2:
        slots["alternative"] = ids[split:]
    evidence = feedback(db, campaign, nodes, selected)
    citable = [e["key"] for e in evidence if e["verdict"] not in ("ACCEPT_BASELINE", "ACCEPT_IMPROVEMENT")]
    citable = citable or [e["key"] for e in evidence]
    schema = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "choices": {
                "type": "object",
                "additionalProperties": False,
                "properties": {k: {"type": "string", "enum": v} for k, v in slots.items()},
                "required": list(slots),
            },
            "evidence_key": {"type": "string", "enum": citable},
            "change": {"type": "string", "minLength": 12, "maxLength": 180},
            "risk": {"type": "string", "minLength": 12, "maxLength": 180},
        },
        "required": ["choices", "evidence_key", "change", "risk"],
    }
    basis = {
        "parent_id": selected["id"],
        "parent_anchor": campaign["selected_anchor"]["sha256"],
        "dataset_id": campaign["dataset_id"],
        "protocol_digest": campaign["protocol"]["digest"],
        "code_digest": campaign["config"]["code_digest"],
        "numeric_digest": numeric_identity(),
        "numeric_threads": campaign["config"]["numeric_threads"],
        "feedback_nodes": [e["node"] for e in evidence],
        "offered_digest": digest(offered),
    }
    context = {
        "task": "Choose one ID per disjoint slot. All offered recipes were deduplicated against the complete memory. Cite the exact evidence_key of a failure or uncertainty when supplied. Explain a concrete parameter change and its risk. An inconclusive result is not a regression. A lower blue loss is insufficient if red Brier worsens. Do not claim improvement before the fixed paired validation.",
        "slots": slots,
        "candidates": candidates,
        "observed_feedback": evidence,
        "question": topic.get("question"),
        "math_tools": {m: run_tool(m) for m in sorted({s["method"] for s in offered})},
        "acceptance": {k: campaign["protocol"][k] for k in ("regression_margin", "red_brier_tolerance")},
        "value_model": {"examples": policy["examples"], "generalization": "NOT_ESTABLISHED"},
        "scope": "DEVELOPMENT_REPLAY;TOOL_SANITY_IS_NOT_PREDICTIVE_EVIDENCE",
    }
    if campaign["protocol"]["version"] == "recent100-tail50-tail10-hits-v4":
        context["task"] = (
            "Choose one novel ID per disjoint slot. Cite the exact evidence_key. Seek incremental red5+ Top100 hit rate or blueTop1 hit rate gains against the parent; both rates must not decline in100/50/10 chronological windows.50 percent is not a promotion threshold. Loss and toy tools alone do not prove hit-rate gains. Explain the parameter change and its risk. Inconclusive is not regression."
        )
        context["observed_feedback"] = [{k: v for k, v in e.items() if k != "node"} for e in evidence]
        context["acceptance"] = {
            "primary": campaign["protocol"]["primary"],
            "promotion": campaign["protocol"]["promotion"],
            "random_history": False,
        }
    memory = recall(db, campaign)
    context["memory"] = memory
    from .research_agent import compact_context

    compact_context(db, campaign, context, candidates, slots, evidence, citable, schema)
    # The immutable plan basis references exactly the evidence retained in this request.
    basis["memory"] = context["memory"]
    basis["feedback_nodes"] = [e["node"] for e in evidence]
    basis["offered_digest"] = digest([v["spec"] for v in candidates.values()])
    selection, receipt = infer(db, artifacts, campaign, job, "CANDIDATE_SELECTION_V2", context, schema, pulse)
    if (
        set(selection) != set(schema["required"])
        or not isinstance(selection["choices"], dict)
        or set(selection["choices"]) != set(slots)
        or selection["evidence_key"] not in citable
        or any(selection["choices"][k] not in allowed for k, allowed in slots.items())
        or any(
            not isinstance(selection[k], str) or not 12 <= len(selection[k]) <= 180
            for k in ("change", "risk")
        )
    ):
        raise DomainError(
            "INVALID_CANDIDATE_SELECTION", "Selection must match the offered IDs and observed evidence"
        )
    proposals = []
    for key in slots:
        cid = selection["choices"][key]
        proposals.append(
            {
                "source": "LOCAL_MODEL_CANDIDATE_SELECTION_V2",
                "spec": candidates[cid]["spec"],
                "candidate_id": cid,
                "pipeline_basis": basis,
                "selection": selection,
                "parameter_changes": {
                    k: {"parent": selected["spec"][k], "candidate": v}
                    for k, v in candidates[cid]["spec"].items()
                    if v != selected["spec"][k]
                },
                "cited_feedback": next(e for e in evidence if e["key"] == selection["evidence_key"]),
                "inference": [receipt],
                "direction_value_model": policy,
                "hypothesis": selection["change"],
                "falsification": selection["risk"],
                "offered_count": len(candidates),
                "novel_pool_count": len(specs),
            }
        )
    return basis, proposals


def skip_stale_node(controller, job, node):
    with controller.db.pool.connection() as c, c.transaction():
        controller.db.fence(c, job)
        campaign = c.execute(
            "SELECT * FROM research_campaigns WHERE id=%s FOR UPDATE", (node["campaign_id"],)
        ).fetchone()
        basis = node["hypothesis"]["pipeline_basis"]
        if campaign["selected_node"] == node["parent_id"] and same_basis(campaign, basis):
            return False
        c.execute(
            "UPDATE research_nodes SET status='STALE_PARENT',decision=%s,completed_at=now() WHERE id=%s",
            (Jsonb({"verdict": "STALE_PARENT", "training_executed": False}), node["id"]),
        )
        c.execute(
            """UPDATE research_recipe_memory SET verdict='STALE_UNTRAINED',last_seen_at=now()
            WHERE dataset_id=%s AND numeric_digest=%s AND spec_digest=%s AND verdict IS NULL""",
            (node["dataset_id"], numeric_identity(), digest(node["spec"])),
        )
        controller.decision(
            c,
            node["campaign_id"],
            node["id"],
            "SKIP_STALE_PARENT",
            {"basis": basis, "actual_parent": campaign["selected_node"], "training_executed": False},
        )
        controller.job(c, node["id"], "RESEARCH_PLAN")
        controller.db.complete(c, job)
    return True


def plan_batch(controller, job, context, pulse):
    db = controller.db
    campaign = db.rows("SELECT * FROM research_campaigns WHERE id=%s", (context["campaign_id"],))[0]
    nodes = db.rows(
        "SELECT * FROM research_nodes WHERE campaign_id=%s ORDER BY created_at,id", (campaign["id"],)
    )
    depth = campaign["config"]["pipeline_depth"]
    if len(nodes) >= campaign["config"]["max_nodes"] or len(pending(nodes)) >= depth:
        with db.pool.connection() as c, c.transaction():
            db.fence(c, job)
            c.execute("SELECT id FROM research_campaigns WHERE id=%s FOR UPDATE", (campaign["id"],))
            remaining = c.execute(
                "SELECT 1 FROM research_nodes WHERE campaign_id=%s AND evaluation IS NULL AND status!='STALE_PARENT'",
                (campaign["id"],),
            ).fetchone()
            if len(nodes) >= campaign["config"]["max_nodes"] and not remaining:
                c.execute(
                    "UPDATE research_campaigns SET status='BATCH_COMPLETE',updated_at=now() WHERE id=%s",
                    (campaign["id"],),
                )
                controller.decision(c, campaign["id"], context["id"], "BATCH_COMPLETE", {"nodes": len(nodes)})
            db.complete(c, job)
        return
    try:
        proposer = propose_batch
        if campaign["config"].get("proposal_policy") == "candidates-v3":
            from .research_review import propose_batch_v3

            proposer = propose_batch_v3
        basis, proposals = proposer(
            controller,
            campaign,
            nodes,
            min(depth - len(pending(nodes)), campaign["config"]["max_nodes"] - len(nodes)),
            job,
            pulse,
        )
    except DomainError as exc:
        if exc.code != "SEARCH_SPACE_EXHAUSTED":
            raise
        # A queued sibling still needs evaluation before the final exhausted state.
        if pending(nodes):
            with db.pool.connection() as c, c.transaction():
                db.fence(c, job)
                db.complete(c, job)
            return
        controller.exhaust(campaign, context, job)
        return
    pulse()
    with db.pool.connection() as c, c.transaction():
        db.fence(c, job)
        current = c.execute(
            "SELECT * FROM research_campaigns WHERE id=%s FOR UPDATE", (campaign["id"],)
        ).fetchone()
        current_nodes = c.execute(
            "SELECT * FROM research_nodes WHERE campaign_id=%s ORDER BY created_at,id", (campaign["id"],)
        ).fetchall()
        pulse()
        if not same_basis(current, basis):
            controller.decision(
                c,
                campaign["id"],
                context["id"],
                "DISCARD_STALE_PLAN",
                {"basis": basis, "selected": current["selected_node"], "offered_proposals": len(proposals)},
            )
            db.complete(c, job)
            return
        capacity = min(
            depth - len(pending(current_nodes)), campaign["config"]["max_nodes"] - len(current_nodes)
        )
        fresh = {
            digest(s)
            for s in untried_specs(db, campaign["dataset_id"], [p["spec"] for p in proposals], connection=c)
        }
        queued, duplicates = 0, 0
        for proposal in proposals:
            if queued >= capacity:
                break
            if digest(proposal["spec"]) not in fresh:
                duplicates += 1
                continue
            siblings = sum(n["parent_id"] == current["selected_node"] for n in current_nodes)
            path = (
                next(n["path"] for n in current_nodes if n["id"] == current["selected_node"])
                + "-"
                + str(siblings + queued + 1)
            )
            child = controller._node(
                c, campaign["id"], path, current["selected_node"], proposal["spec"], proposal
            )
            controller.decision(
                c,
                campaign["id"],
                child,
                "EXPLORE_NEW_DIRECTION",
                {
                    "from_node": current["selected_node"],
                    "to_path": path,
                    "basis": basis,
                    "call_id": proposal["inference"][0]["call_id"],
                },
            )
            fresh.discard(digest(proposal["spec"]))
            queued += 1
        controller.decision(
            c,
            campaign["id"],
            context["id"],
            "PROPOSAL_BATCH_RESULT",
            {
                "basis": basis,
                "selected": len(proposals),
                "queued": queued,
                "duplicates_filtered_at_commit": duplicates,
                "queue_depth_limit": depth,
                "pending_after": len(pending(current_nodes)) + queued,
                "feedback_completed_during_planning": [
                    n["id"]
                    for n in current_nodes
                    if n["evaluation"] and n["id"] not in {x["id"] for x in nodes if x["evaluation"]}
                ],
            },
        )
        db.complete(c, job)
