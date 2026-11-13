"""Replay immutable provider outputs before certifying operational recovery.

No generation, changed profile, answer repair or replacement mechanism result.
"""

import argparse
import json

from psycopg.types.json import Jsonb

from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest
from dehps_next.qwen_recovery import certificate_id
from dehps_next.research_output_guard import VERSION, identity, repetition
from dehps_next.research_selection import mechanism_metrics
from dehps_next.research_short_thinking import performance


def first_trigger(text):
    return next((n for n in range(1, len(text) + 1) if repetition(text[:n])), None)


def verify(db, failed_audit):
    state = db.rows("SELECT * FROM qwen_selection_state WHERE id=1")[0]
    profile = db.rows("SELECT * FROM qwen_selection_profiles WHERE id=%s", (state["profile_id"],))[0]
    study = profile["mechanism_study"]
    original = db.rows("SELECT payload FROM research_review_results WHERE study_id=%s", (study,))[0]["payload"]
    quality = mechanism_metrics(db, study, profile["config"])
    latency = performance(db, study, profile["config"])
    assert original["passed"] and latency["passed"]
    assert quality["semantic_accuracy"] >= .9 and quality["recipe_stability"] >= .8
    assert quality["first_position_fraction"] <= .5 and quality["accuracy_feedback_lift"] >= .2
    rows = db.rows("SELECT pair,arm,payload FROM research_review_selections WHERE study_id=%s ORDER BY pair,arm", (study,))
    assert len(rows) == 144
    rejections = []
    for row in rows:
        metrics = row["payload"]["actual_call"]["metrics"]
        first = metrics["thinking_receipt"]["metrics"]["raw_thinking"]
        answer = metrics["raw_completion"]
        rejected = first_trigger(first) or first_trigger(answer)
        if rejected:
            rejections.append({"pair": row["pair"], "arm": row["arm"],
                               "valid": row["payload"]["valid"], "trigger_character": rejected})
    valid_rejected = sum(r["valid"] for r in rejections)
    failure = db.rows("SELECT * FROM qwen_selection_audits WHERE id=%s", (failed_audit,))[0]
    p = failure["payload"]
    native = p["failed_qwen_call"]
    assert p["profile_id"] == profile["id"] and native["state"] == "FAILED"
    assert native["metrics"]["failure_code"] == "LOCAL_MODEL_TRUNCATED"
    metrics = native["metrics"]
    first = metrics["thinking_receipt"]["metrics"]["raw_thinking"]
    trigger = first_trigger(first)
    header = {"kind": "QWEN_OPERATIONAL_OUTPUT_RECOVERY_V1", "guard_version": VERSION,
              "guard_identity": identity(), "profile_id": profile["id"],
              "mechanism_study": study, "source_slots_sha256": digest(rows),
              "failed_audit": failed_audit, "failed_native_sha256": digest(native),
              "policy": "same accepted profile, budgets and gates; retain every old outcome; reject loops; new-task-only cooldown with20 fresh feedback; original draw gate; actual success clears reason"}
    result = {"passed": valid_rejected == 0 and trigger is not None,
              "protocol_sha256": digest(header), "source_slots": len(rows),
              "source_valid_slots": sum(bool(r["payload"]["valid"]) for r in rows),
              "source_invalid_slots_preserved": sum(not r["payload"]["valid"] for r in rows),
              "previous_valid_rejected": valid_rejected, "all_rejections": rejections,
              "original_failure_detected": trigger is not None, "failed_prefix_trigger_character": trigger,
              "failed_prefix_characters": len(first), "source_quality": quality,
              "source_latency": latency,
              "scope": "IMMUTABLE_ACTUAL_OUTPUT_REPLAY;NOT_NEW_MODEL_ACCEPTANCE_OR_LIVE_CLOSURE"}
    return header, result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--failed-audit", type=int, required=True)
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args()
    db = Database(Settings.from_env())
    try:
        header, result = verify(db, args.failed_audit)
        if args.register:
            assert result["passed"]
            study = certificate_id(header["profile_id"])
            with db.pool.connection() as c, c.transaction():
                c.execute("INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                          (study, Jsonb(header), digest(header)))
                assert c.execute("SELECT sha256 FROM research_review_studies WHERE id=%s", (study,)).fetchone()["sha256"] == digest(header)
                c.execute("INSERT INTO research_review_results(study_id,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING", (study, Jsonb(result)))
                assert c.execute("SELECT payload FROM research_review_results WHERE study_id=%s", (study,)).fetchone()["payload"] == result
        print(json.dumps({"header": header, "result": result}))
    finally:
        db.close()


if __name__ == "__main__":
    main()
