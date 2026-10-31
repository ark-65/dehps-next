"""Compact real choices, cross-campaign paired feedback and grounded per-choice hypotheses."""

from psycopg.types.json import Jsonb

from .domain import canonical, digest
from .errors import DomainError
from .research_agent import infer
from .research_memory import feedback_contract, recall, untried_specs
from .research_policy import train_policy
from .research_search import extended_specs, novel_specs

PARAMS = ("method", "window", "hidden", "epochs", "learning_rate", "weight_decay", "train_history")
AXES = ("m", "w", "h", "ep", "lr", "wd", "hist")
WINDOWS = ("recent", "recent50", "recent10")


def counts(business):
    return [business["windows"][w][k] for w in WINDOWS for k in ("red5_periods", "blue_hits")]


def spec_row(spec):
    return [spec[k] for k in PARAMS]


def changes(parent, child):
    return {k: {"parent": parent[k], "candidate": child[k]} for k in PARAMS if parent[k] != child[k]}


def cross_round_feedback(db, campaign, selected):
    """Condition all feedback on the exact parent outcomes, not just the dataset."""
    parent = selected["evaluation"]["business"]
    args = (feedback_contract(campaign), parent["periods_digest"])
    base = """ FROM research_memory_events WHERE contract=%s AND kind='EVALUATION'
        AND parent_id IS NOT NULL
        AND payload->'decision'->'business'->'parent'->>'periods_digest'=%s"""
    red = " OR ".join(
        f"(payload->'decision'->'business'->'paired_windows'->'{w}'->>'red5_rate')::float<0" for w in WINDOWS
    )
    blue = " OR ".join(
        f"(payload->'decision'->'business'->'paired_windows'->'{w}'->>'blue_rate')::float<0" for w in WINDOWS
    )
    families = db.rows(
        "SELECT spec->>'method' AS method,count(*) AS n,max(seq) AS last_seq,"
        "count(*) FILTER(WHERE payload->>'verdict'='ACCEPT_IMPROVEMENT') AS improved,"
        "count(*) FILTER(WHERE payload->>'verdict'='PRUNE_REGRESSION') AS pruned,"
        f"count(*) FILTER(WHERE {red}) AS red_risk,count(*) FILTER(WHERE {blue}) AS blue_risk"
        + base
        + " GROUP BY spec->>'method' ORDER BY method",
        args,
    )
    candidates = db.rows(
        "SELECT DISTINCT ON(spec->>'method') seq,node_id,spec,payload-'period_outcomes'-'origin_provenance' AS p"
        + base
        + " AND payload->>'verdict' IN ('INCONCLUSIVE','PRUNE_REGRESSION')"
        " ORDER BY spec->>'method',(payload->>'verdict'='PRUNE_REGRESSION') DESC,seq DESC",
        args,
    )
    # Include a real red/blue tradeoff, rather than only the most recent failure.
    tradeoffs = db.rows(
        "SELECT seq,node_id,spec,payload-'period_outcomes'-'origin_provenance' AS p"
        + base
        + " AND payload->>'verdict' IN ('INCONCLUSIVE','PRUNE_REGRESSION')"
        " ORDER BY (payload->'business'->'windows'->'recent'->>'blue_hits')::int DESC,seq DESC LIMIT 1",
        args,
    )
    seen, evidence = set(), []
    for row in candidates + tradeoffs:
        if row["node_id"] in seen:
            continue
        seen.add(row["node_id"])
        evidence.append(
            {
                "key": f"f{len(evidence)}",
                "node": row["node_id"],
                "seq": row["seq"],
                "campaign": row["p"]["campaign"],
                "spec": row["spec"],
                "verdict": row["p"]["verdict"],
                "hits": counts(row["p"]["business"]),
                "paired_windows": row["p"]["decision"]["business"]["paired_windows"],
            }
        )
        if len(evidence) == 4:
            break
    return {
        "contract": args[0],
        "parent_periods_digest": args[1],
        "families": families,
        "evidence": evidence,
        "trials": sum(r["n"] for r in families),
        "through_seq": max((r["last_seq"] for r in families), default=0),
        "scope": "COMPARABLE_RECIPE_TRIALS;SAME100_ISSUES_NOT_ADDITIONAL_DRAWS",
    }


def candidate_pool(db, campaign, selected, value, count):
    topic = campaign["config"].get("topic") or {
        "name": "regularized-history",
        "methods": ["fft", "ridge", "newton"],
    }
    minimum = 6 if count == 2 else 3
    specs = novel_specs(db, campaign["dataset_id"], campaign["config"]["code_digest"], topic)
    if len(specs) < minimum:
        more = extended_specs(db, campaign["dataset_id"], topic, minimum=minimum)
        specs = untried_specs(db, campaign["dataset_id"], specs + more)
    if len(specs) < minimum:
        raise DomainError("INSUFFICIENT_REAL_CHOICES", "Do not call Qwen with a predetermined selection")
    ranked = sorted(specs, key=lambda s: (-value(s, selected["evaluation"]["summary"]), digest(s)))
    parent = selected["spec"]
    local = sorted(ranked, key=lambda s: len(changes(parent, s)))
    offer, axes = [], set()
    for spec in local:
        axis = tuple(changes(parent, spec))
        if axis not in axes:
            axes.add(axis)
            offer.append(spec)
        if len(offer) == 3:
            break
    for spec in ranked:
        if len(offer) >= 3:
            break
        if spec not in offer:
            offer.append(spec)
    groups = {(s["method"], s["window"], s["hidden"], s["train_history"]) for s in offer}
    for spec in ranked:
        group = (spec["method"], spec["window"], spec["hidden"], spec["train_history"])
        if spec not in offer and group not in groups:
            offer.append(spec)
            groups.add(group)
        if len(offer) == 6:
            break
    for spec in ranked:
        if len(offer) == 6:
            break
        if spec not in offer:
            offer.append(spec)
    # Stable shuffling within each group avoids exposing value-rank through the first ID.
    offer = sorted(offer[:3], key=lambda s: digest([selected["id"], s])) + sorted(
        offer[3:6], key=lambda s: digest([selected["id"], s])
    )
    return offer, len(specs)


def review_context(parent_spec, parent_business, offered, memory, *, count=2, with_feedback=True):
    offered = offered[:6]
    candidates = {f"c{i}": s for i, s in enumerate(offered)}
    ids = list(candidates)
    groups = {"repair": ids[:3], "explore": ids[3:6]} if count == 2 else {"choose": ids}
    if any(len({digest(candidates[k]) for k in v}) < 3 for v in groups.values()):
        raise DomainError(
            "INSUFFICIENT_REAL_CHOICES", "Every review group needs at least three distinct candidates"
        )
    evidence = memory["evidence"] if with_feedback else []
    if not evidence:
        evidence = [
            {
                "key": "p",
                "spec": parent_spec,
                "hits": counts(parent_business),
                "node": None,
                "verdict": "ACCEPTED_PARENT",
                "paired_windows": None,
            }
        ]
    context = {
        "task": "Pick one candidate c in EACH named group, cite evidence e and intended goal g. Candidate outcomes are UNKNOWN;the controller records exact parameter changes.",
        "cols": list(AXES),
        "groups": groups,
        "C": {k: spec_row(s) for k, s in candidates.items()},
        "P": spec_row(parent_spec),
        "parent_hits": counts(parent_business),
        "hits": "[red5+Top100,blueTop1] for100/50/10;all nested in100 issues",
        "rule": "One100-rate improves;both rates nondecreasing in100/50/10.No50% gate.",
        "F": {e["key"]: [spec_row(e["spec"]), e["hits"], e["verdict"]] for e in evidence},
    }
    if with_feedback:
        context["family_cols"] = ["method", "trials", "red_risk", "blue_risk", "improved"]
        context["history"] = [
            [r["method"], r["n"], r["red_risk"], r["blue_risk"], r["improved"]] for r in memory["families"]
        ]
        context["memory_trials"] = memory["trials"]
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": list(groups),
        "properties": {
            name: {
                "type": "object",
                "additionalProperties": False,
                "required": ["c", "e", "g"],
                "properties": {
                    "c": {"type": "string", "enum": allowed},
                    "e": {"type": "string", "enum": [e["key"] for e in evidence]},
                    "g": {"type": "string", "enum": ["red", "blue", "stable"]},
                },
            }
            for name, allowed in groups.items()
        },
    }
    return context, schema, candidates, groups, evidence


def select(
    db,
    artifacts,
    campaign,
    job,
    pulse,
    parent_spec,
    parent_business,
    offered,
    memory,
    *,
    count=2,
    with_feedback=True,
):
    context, schema, candidates, groups, evidence = review_context(
        parent_spec, parent_business, offered, memory, count=count, with_feedback=with_feedback
    )
    # Compact column arrays preserve every candidate, evidence row and family total.
    if len(canonical({"context": context, "format": schema}).encode()) > 2600:
        raise DomainError(
            "MEMORY_CONTEXT_TOO_LARGE",
            "Keep all alternatives and failure facts;never trim into forced choices",
        )
    stage = "CANDIDATE_SELECTION_V3_" + ("FEEDBACK" if with_feedback else "NO_FEEDBACK")
    reply, receipt = infer(db, artifacts, campaign, job, stage, context, schema, pulse)
    try:
        if set(reply) != set(groups):
            raise ValueError("One grounded pick per group is required")
        picks = []
        for group, ids in groups.items():
            choice = reply[group]
            if set(choice) != {"c", "e", "g"} or choice["c"] not in ids:
                raise ValueError("Candidate must belong to its own review group")
            cited = next((e for e in evidence if e["key"] == choice["e"]), None)
            if cited is None or choice["g"] not in ("red", "blue", "stable"):
                raise ValueError("Evidence and intended goal must be supplied")
            spec = candidates[choice["c"]]
            delta = changes(parent_spec, spec)
            if not delta:
                raise ValueError("Selected candidate must actually change the parent")
            differences = ", ".join(f"{k} {v['parent']} -> {v['candidate']}" for k, v in delta.items())
            hypothesis = (
                f"Candidate {choice['c']}: {differences};"
                f"hypothesis seeks {choice['g']} progress against evidence {choice['e']} ({cited['verdict']});unvalidated"
            )
            picks.append(
                {
                    "candidate_id": choice["c"],
                    "spec": spec,
                    "parameter_changes": delta,
                    "cited_feedback": cited,
                    "selection": choice,
                    "hypothesis": hypothesis,
                    "falsification": "Reject or retain uncertainty using unchanged paired100/50/10;no candidate outcome assumed",
                }
            )
    except (ValueError, KeyError, TypeError) as exc:
        with db.pool.connection() as c:
            c.execute(
                "UPDATE research_model_calls SET state='FAILED',metrics=metrics||%s WHERE id=%s",
                (Jsonb({"failure_code": "INVALID_GROUNDED_REVIEW"}), receipt["call_id"]),
            )
        raise DomainError("INVALID_GROUNDED_REVIEW", str(exc)) from exc
    return (
        picks,
        receipt,
        {
            "context": context,
            "schema": schema,
            "reply": reply,
            "offered_digest": digest(offered),
            "memory": memory,
            "minimum_group_options": min(map(len, groups.values())),
            "input_digest": digest(context),
            "with_feedback": with_feedback,
        },
    )


def propose_batch_v3(controller, campaign, nodes, count, job, pulse):
    db, artifacts = controller.db, controller.artifacts
    parent = next(n for n in nodes if n["id"] == campaign["selected_node"])
    value, policy = train_policy(db, artifacts, campaign, job)
    offered, pool_size = candidate_pool(db, campaign, parent, value, count)
    memory = cross_round_feedback(db, campaign, parent)
    head = recall(db, campaign, force=True, reason="CROSS_ROUND_GROUNDED_REVIEW")
    pulse()
    picks, receipt, proof = select(
        db,
        artifacts,
        campaign,
        job,
        pulse,
        parent["spec"],
        parent["evaluation"]["business"],
        offered,
        memory,
        count=count,
    )
    basis = {
        "parent_id": parent["id"],
        "parent_anchor": campaign["selected_anchor"]["sha256"],
        "dataset_id": campaign["dataset_id"],
        "protocol_digest": campaign["protocol"]["digest"],
        "code_digest": campaign["config"]["code_digest"],
        "numeric_digest": campaign["config"]["numeric_digest"],
        "numeric_threads": campaign["config"]["numeric_threads"],
        "feedback_nodes": [e["node"] for e in memory["evidence"]],
        "offered_digest": digest(offered),
        "memory": head,
    }
    for pick in picks:
        pick.update(
            source="LOCAL_MODEL_CANDIDATE_SELECTION_V3",
            pipeline_basis=basis,
            inference=[receipt],
            direction_value_model=policy,
            offered_count=len(offered),
            novel_pool_count=pool_size,
            review_evidence={
                "input_digest": proof["input_digest"],
                "family_summary": memory["families"],
                "through_seq": memory["through_seq"],
                "minimum_group_options": proof["minimum_group_options"],
                "selection": pick["selection"],
            },
        )
    return basis, picks
