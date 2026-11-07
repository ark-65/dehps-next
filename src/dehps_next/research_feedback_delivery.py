"""Keep real Qwen-selected batch outcomes until their actual subsequent delivery."""

import json

from .domain import digest
from .errors import DomainError
from .research_memory import insert_event


def delivery_key(profile, node):
    return f"qwen-feedback-delivered:{profile}:{node}"


def batch_feedback(db, base, args, profile):
    if not profile:
        return []
    own = (
        base
        + " AND payload->'review_evidence'->>'selection_source'='QWEN_COMPARATIVE'"
        " AND payload->'review_evidence'->>'profile_id'=%s"
    )
    columns = "SELECT seq,node_id,spec,payload-'period_outcomes'-'origin_provenance' AS p"
    # An input watermark alone never acknowledges an omitted outcome.
    first = db.rows(
        columns + own
        + " AND NOT EXISTS (SELECT 1 FROM research_memory_events ack WHERE ack.event_key="
        "'qwen-feedback-delivered:' || %s || ':' || research_memory_events.node_id)"
        " ORDER BY seq LIMIT 1",
        (*args, profile, profile),
    )
    if not first:
        first = db.rows(columns + own + " ORDER BY seq DESC LIMIT 1", (*args, profile))
    if not first:
        return []
    batch = first[0]["p"]["review_evidence"]["input_digest"]
    rows = db.rows(
        columns + own
        + " AND payload->'review_evidence'->>'input_digest'=%s ORDER BY seq LIMIT 3",
        (*args, profile, batch),
    )
    if len(rows) > 2:
        raise DomainError("QWEN_FEEDBACK_BATCH_SIZE", "A selection batch contains at most two outcomes")
    return rows


def delivery_records(db, memory, proof, receipt, artifacts):
    targets = memory.get("qwen_feedback_targets", [])
    if not targets:
        return []
    call = db.rows("SELECT * FROM research_model_calls WHERE id=%s", (receipt["call_id"],))[0]
    metrics = call["metrics"]
    if (
        call["state"] != "SUCCEEDED"
        or digest(metrics["selection_profile"]) != proof["profile_id"]
        or call["model_digest"] != receipt["model_digest"]
        or not metrics.get("prompt_eval_count") or not metrics.get("eval_count")
    ):
        raise DomainError("QWEN_FEEDBACK_RECEIPT", "Require a successful actual model call")
    request = metrics.get("logical_request", call["request"])
    logical = json.loads(artifacts.read(request))
    context = json.loads(logical["messages"][1]["content"])
    context.pop("output_contract", None)
    if (
        digest(context) != proof["input_digest"]
        or digest(proof["context"]) != proof["input_digest"]
    ):
        raise DomainError("QWEN_FEEDBACK_INPUT_MISMATCH", "Require the actual generated request")
    if metrics.get("thinking_receipt"):
        from .research_short_thinking import render, validate_receipt

        validate_receipt(metrics, metrics["selection_profile"])
        prefix = json.loads(artifacts.read(metrics["thinking_receipt"]["request"]))
        if prefix["prompt"] != render(logical["messages"]):
            raise DomainError("QWEN_FEEDBACK_INPUT_MISMATCH", "Actual thinking prefix must match")
    records = []
    for target in targets:
        keys = [
            e["key"] for e in context["evidence"]
            if digest(e["spec"]) == target["recipe_digest"]
            and e["hits"] == target["hits"] and e["verdict"] == target["verdict"]
        ]
        if not keys or memory["through_seq"] < target["seq"] or memory["contract"] != target["contract"]:
            raise DomainError("QWEN_FEEDBACK_DELIVERY_INCOMPLETE", "Every selected batch outcome must be sent")
        records.append({
            **target, "call_id": receipt["call_id"], "profile_id": proof["profile_id"],
            "actual_request": request, "input_digest": proof["input_digest"],
            "feedback_keys": keys,
        })
    return records


def record_deliveries(c, campaign, records, audit):
    for record in records:
        insert_event(
            c, campaign, record["contract"],
            delivery_key(record["profile_id"], record["node"]), "QWEN_FEEDBACK_DELIVERY",
            {**record, "audit_id": audit}, node_id=record["node"],
        )
