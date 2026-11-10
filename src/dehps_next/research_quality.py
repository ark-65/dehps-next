"""Append measured batch outcomes; never infer predictive progress from work counts."""

from .domain import digest
from .research_frontier import NAME
from .research_memory import feedback_contract, insert_event


def review_completed(db):
    campaigns = db.rows("""SELECT r.* FROM research_campaigns r
        WHERE r.program_id='autonomous-v2' AND r.topic=%s AND r.status='BATCH_COMPLETE'
        AND NOT EXISTS(SELECT 1 FROM research_memory_events e WHERE e.event_key='batch-quality:'||r.id)
        ORDER BY r.created_at DESC LIMIT 4""", (NAME,))
    reviewed = []
    for campaign in campaigns:
        rows = db.rows("""SELECT id,parent_id,spec,status,evaluation->'business' AS business,
            evaluation->'execution' AS execution,decision->'business'->'paired_windows' AS deltas,
            decision->'business'->'parent'->'windows' AS paired_parent_windows
            FROM research_nodes WHERE campaign_id=%s ORDER BY created_at,id""", (campaign["id"],))
        parents = [n for n in rows if n["parent_id"] is None and n["business"]]
        if len(parents) != 1:
            continue  # Optional graph may have retired; immutable node facts remain authoritative.
        children = [n for n in rows if n["parent_id"] and n["business"] and n["deltas"]]
        diagnosis = {"evaluated_candidates": len(children), "red_vetoes": 0,
                     "blue_vetoes": 0, "no_recent_progress": 0, "nested_only_vetoes": 0}
        candidates = []
        for n in children:
            delta = n["deltas"]
            red = any(w["red5_rate"] < 0 for w in delta.values())
            blue = any(w["blue_rate"] < 0 for w in delta.values())
            recent_progress = any(v > 0 for v in delta["recent"].values())
            diagnosis["red_vetoes"] += red
            diagnosis["blue_vetoes"] += blue
            diagnosis["no_recent_progress"] += not recent_progress
            diagnosis["nested_only_vetoes"] += recent_progress and (red or blue)
            candidates.append({"node": n["id"], "parent_node": n["parent_id"],
                               "paired_parent_windows": n["paired_parent_windows"],
                               "spec": n["spec"], "verdict": n["status"],
                               "windows": n["business"]["windows"], "paired_deltas": delta,
                               "execution": n["execution"]})
        payload = {"campaign": campaign["id"], "dataset": campaign["dataset_id"],
                   "protocol_digest": campaign["protocol"]["digest"],
                   "parent_spec": parents[0]["spec"], "parent_spec_digest": digest(parents[0]["spec"]),
                   "parent_windows": parents[0]["business"]["windows"], "candidates": candidates,
                   "promotions": sum(n["status"] == "ACCEPT_IMPROVEMENT" for n in children),
                   "diagnosis": diagnosis,
                   "untrained_skips": sum(n["status"] == "STALE_PARENT" for n in rows),
                   "scope": "PAIRED_HISTORICAL_BATCH_REVIEW;100_LABELS_NOT_CANDIDATE_COUNT;NOT_FORWARD",
                   "next_action": "KEEP_EXISTING_PROMOTION_GATES;DIAGNOSE_AND_CHANGE_QUESTION_AT_BLOCK_BOUNDARY"}
        payload["source_facts_sha256"] = digest({k: payload[k] for k in
            ("dataset", "protocol_digest", "parent_windows", "candidates", "untrained_skips")})
        with db.pool.connection() as c, c.transaction():
            insert_event(c, campaign, feedback_contract(campaign), "batch-quality:" + campaign["id"],
                         "BATCH_QUALITY_REVIEW", payload)
        reviewed.append({"campaign": campaign["id"], "promotions": payload["promotions"],
                         "diagnosis": diagnosis})
    return reviewed


def recent_diagnosis(c, dataset, numeric, parent):
    rows = c.execute("""SELECT seq,payload FROM research_memory_events
        WHERE dataset_id=%s AND numeric_digest=%s AND kind='BATCH_QUALITY_REVIEW'
        ORDER BY seq DESC LIMIT 8""", (dataset, numeric)).fetchall()
    rows = [r for r in rows if r["payload"]["parent_spec_digest"] == digest(parent)][:4]
    return {"review_events": [r["seq"] for r in rows],
            **{k: sum(r["payload"]["diagnosis"][k] for r in rows)
               for k in ("evaluated_candidates", "red_vetoes", "blue_vetoes", "no_recent_progress", "nested_only_vetoes")},
            "scope": "RECENT_COMPARABLE_CANDIDATES;NOT_ADDITIONAL_INDEPENDENT_DRAW_LABELS"}
