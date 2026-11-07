"""Require both frozen trained candidates in one later actual primary Qwen input."""

import argparse
import json

from psycopg.types.json import Jsonb

from dehps_next.artifacts import Artifacts
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest, now, timestamp
from dehps_next.research_feedback_delivery import delivery_key
from dehps_next.research_review import counts
from dehps_next.research_short_thinking import render, validate_receipt


def actual_input(db, artifacts, audit, profile):
    call = db.rows("SELECT * FROM research_model_calls WHERE id=%s", (audit["call_id"],))[0]
    m = call["metrics"]
    assert call["state"] == "SUCCEEDED" and digest(m["selection_profile"]) == profile
    validate_receipt(m, m["selection_profile"])
    first = db.rows("SELECT * FROM research_model_calls WHERE id=%s", (m["thinking_call_id"],))[0]
    assert first["state"] == "SUCCEEDED"
    assert all(first[k] == call[k] for k in ("campaign_id", "job_id", "attempt_id", "model_digest"))
    assert first["request"] == m["thinking_receipt"]["request"]
    for receipt in (call, first):
        gpu = receipt["metrics"]["offload"]
        assert gpu["size_vram"] >= gpu["size"] > 0 and gpu["context_length"] == 16384
        assert receipt["metrics"]["prompt_eval_count"] > 0 and receipt["metrics"]["eval_count"] > 0
    logical = json.loads(artifacts.read(m["logical_request"]))
    prefix = json.loads(artifacts.read(first["request"]))
    answer = json.loads(artifacts.read(call["request"]))
    assert prefix["prompt"] == render(logical["messages"])
    assert answer["prompt"] == prefix["prompt"] + m["raw_thinking"] + "\n</think>\n\n"
    assert prefix["options"]["num_predict"] == 512 and answer["options"]["num_predict"] == 1024
    context = json.loads(logical["messages"][1]["content"])
    context.pop("output_contract", None)
    assert digest(context) == audit["payload"]["input_digest"]
    return call, first, context


def verify(db, artifacts, study, persist=False):
    frozen = db.rows("SELECT * FROM research_review_studies WHERE id=%s", (study,))[0]
    p = frozen["protocol"]
    assert digest(p) == frozen["sha256"] and p["kind"] == "QWEN_FEEDBACK_CLOSURE_V1"
    assert p["same_later_call_required"] and len(p["targets"]) == 2
    origin = db.rows("SELECT * FROM qwen_selection_audits WHERE id=%s", (p["original_audit"],))[0]
    original, _, _ = actual_input(db, artifacts, origin, p["profile"])
    assert original["id"] == p["original_call"] and origin["source"] == "QWEN_COMPARATIVE"
    targets = []
    for target in p["targets"]:
        n = db.rows("SELECT * FROM research_nodes WHERE id=%s", (target["node"],))[0]
        memory = db.rows("SELECT * FROM research_memory_events WHERE seq=%s", (target["seq"],))[0]
        assert digest(memory["payload"]) == target["memory_sha256"]
        assert memory["node_id"] == n["id"] and memory["contract"] == target["contract"]
        assert digest(n["spec"]) == target["recipe_digest"] and n["status"] == target["verdict"]
        assert counts(n["evaluation"]["business"]) == target["hits"]
        key = n["hypothesis"]["selection"]["candidate"]
        assert origin["payload"]["candidate_identities"][key] == digest(n["spec"])
        assert key in origin["payload"]["reply"]["selection"].values()
        assert any(r["call_id"] == original["id"] for r in n["hypothesis"]["inference"])
        execution = n["evaluation"]["execution"]
        assert execution["origin_fits_executed_this_attempt"] > 0
        assert execution["gradient_steps_executed_this_attempt"] > 0
        assert execution["all_origin_parameters_updated"]
        artifacts.read(n["evaluation"]["publication_anchor"])
        artifacts.read(n["evaluation"]["scores"])
        targets.append(target)
    observations = []
    for audit in db.rows("""SELECT * FROM qwen_selection_audits WHERE source='QWEN_COMPARATIVE'
        AND payload->>'profile_id'=%s AND created_at>%s ORDER BY id LIMIT 64""",
        (p["profile"], p["minimum_later_call_start"])):
        call, first, context = actual_input(db, artifacts, audit, p["profile"])
        matches = []
        for target in targets:
            keys = [e["key"] for e in context["evidence"]
                    if digest(e["spec"]) == target["recipe_digest"] and e["hits"] == target["hits"]
                    and e["verdict"] == target["verdict"]]
            valid = bool(keys) and call["created_at"] > timestamp(target["completed_at"])
            valid = valid and audit["payload"]["through_seq"] >= target["seq"]
            valid = valid and audit["payload"]["feedback_contract"] == target["contract"]
            ack = db.rows("SELECT payload FROM research_memory_events WHERE event_key=%s",
                          (delivery_key(p["profile"], target["node"]),))
            acknowledged = bool(ack and ack[0]["payload"]["call_id"] == call["id"])
            matches.append({"node": target["node"], "received": valid,
                            "feedback_keys": keys, "delivery_acknowledged": acknowledged})
        observations.append({"call_id": call["id"], "matches": matches})
        if not all(m["received"] and m["delivery_acknowledged"] for m in matches):
            continue
        result = {
            "state": "BOTH_FEEDBACK_CLOSED_LOOP_VERIFIED", "closed_loop_verified": True,
            "both_received_in_same_call": True, "study": study, "contract_sha256": frozen["sha256"],
            "observed_at": now().isoformat(), "original_call": original["id"],
            "later_call": call["id"], "later_audit": audit["id"], "targets": targets,
            "matches": matches, "actual_request": call["metrics"]["logical_request"],
            "native_receipts": [call, first],
            "proof_campaigns": sorted(set(p["target_campaigns"] + [call["campaign_id"]])),
            "scope": "ACTUAL_PRIMARY_BOTH_CANDIDATES_FITS_AND_LATER_FEEDBACK;NOT_PREDICTIVE_BENEFIT",
        }
        if persist:
            with db.pool.connection() as c, c.transaction():
                c.execute("INSERT INTO research_review_results(study_id,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                          (study, Jsonb(json.loads(json.dumps(result, default=str)))))
                result = c.execute("SELECT payload FROM research_review_results WHERE study_id=%s",
                                   (study,)).fetchone()["payload"]
                assert result["both_received_in_same_call"] and result["contract_sha256"] == frozen["sha256"]
        return result
    return {"state": "WAITING_BOTH_FEEDBACK_IN_ACTUAL_CALL", "closed_loop_verified": False,
            "both_received_in_same_call": False, "observed_at": now().isoformat(),
            "study": study, "observations": observations}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", required=True)
    parser.add_argument("--persist", action="store_true")
    args = parser.parse_args()
    db = Database(Settings.from_env())
    try:
        assert db.rows("SELECT current_database() AS n")[0]["n"] == "dehps_next"
        print(json.dumps(verify(db, Artifacts(db.settings, db), args.study, args.persist), default=str))
    finally:
        db.close()


if __name__ == "__main__":
    main()
