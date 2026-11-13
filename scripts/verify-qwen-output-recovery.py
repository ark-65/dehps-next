"""Replay immutable provider outputs before certifying operational recovery.

No generation, answer repair or replacement mechanism result. A new execution
profile must have its own completed qualification before historical failure replay.
"""

import argparse
import copy
import json

from psycopg.types.json import Jsonb

from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest
from dehps_next.qwen_recovery import certificate_id
from dehps_next.release import code_identity, numeric_identity
from dehps_next.research_output_guard import VERSION, identity, repetition
from dehps_next.research_selection import mechanism_metrics
from dehps_next.research_short_thinking import performance, validate_profile


def first_trigger(text):
    return next((n for n in range(1, len(text) + 1) if repetition(text[:n])), None)


def semantic_profile(config):
    validate_profile(config)
    result = copy.deepcopy(config)
    result.pop("backend")
    assert result["options"].pop("num_batch", 512) == 512
    return result


def verify(db, failed_audit, *, profile_id=None):
    state = db.rows("SELECT * FROM qwen_selection_state WHERE id=1")[0]
    profile = db.rows("SELECT * FROM qwen_selection_profiles WHERE id=%s",
                      (profile_id or state["profile_id"],))[0]
    assert digest(profile["config"]) == profile["id"]
    study = profile["mechanism_study"]
    qualification_sha = None
    if profile_id is not None:
        qualified = db.rows("""SELECT s.protocol,s.sha256,r.payload
            FROM research_review_studies s JOIN research_review_results r ON r.study_id=s.id
            WHERE s.id=%s""", (study + "-short-qualification",))
        assert len(qualified) == 1, "Explicit execution profile requires its own completed qualification"
        qualification = qualified[0]
        frozen, passed = qualification["protocol"], qualification["payload"]
        assert digest(frozen) == qualification["sha256"]
        assert frozen.get("controller_source") == code_identity() and frozen.get("numeric") == numeric_identity(), \
            "Explicit profile qualification must match the current source and numeric contract"
        assert frozen.get("profile") == profile["config"]
        assert frozen.get("execution_candidate", {}).get("output_guard") == identity(), \
            "Explicit profile requires the current guard and its own execution candidate"
        assert passed["passed"] and passed["profile_id"] == profile["id"]
        assert passed["mechanism_study"] == study and passed["mechanism_passed"]
        assert passed["primary_observations_complete"] and passed["primary_overlaps"] == []
        binding = passed["execution_binding"]
        assert binding["complete"] and binding["logical_calls"] == 144 and binding["native_calls"] == 288
        qualification_sha = digest(passed)
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
    assert native["state"] == "FAILED" and native["id"] == failure["call_id"]
    if profile_id is None:
        assert p["profile_id"] == profile["id"]
    else:
        original_profile = db.rows("SELECT config FROM qwen_selection_profiles WHERE id=%s",
                                   (p["profile_id"],))
        assert len(original_profile) == 1
        failed_profile = original_profile[0]["config"]
        assert digest(failed_profile) == p["profile_id"]
        assert semantic_profile(failed_profile) == semantic_profile(profile["config"]), \
            "Historical failure must use the same model, framing, sampling, budgets and cadence"
        assert native["model_digest"] == profile["config"]["model_digest"]
        if native["metrics"].get("selection_profile") is not None:
            assert native["metrics"]["selection_profile"] == failed_profile
    assert native["metrics"]["failure_code"] == "LOCAL_MODEL_TRUNCATED"
    metrics = native["metrics"]
    first = metrics["thinking_receipt"]["metrics"]["raw_thinking"]
    trigger = first_trigger(first)
    header = {"kind": "QWEN_OPERATIONAL_OUTPUT_RECOVERY_V1", "guard_version": VERSION,
              "guard_identity": identity(), "profile_id": profile["id"],
              "mechanism_study": study, "source_slots_sha256": digest(rows),
              "failed_audit": failed_audit, "failed_native_sha256": digest(native),
              "policy": "same accepted profile, budgets and gates; retain every old outcome; reject loops; new-task-only cooldown with20 fresh feedback; original draw gate; actual success clears reason"}
    if profile_id is not None:
        header.update(failed_profile_id=p["profile_id"], execution_qualification_sha256=qualification_sha,
                      controller_source=code_identity(), numeric=numeric_identity(),
                      historical_failure_scope="SAME_SEMANTIC_CONTRACT;NEW_EXECUTION_HAS_OWN_FRESH144_HOST_BOUND_QUALIFICATION")
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
    parser.add_argument("--profile-id", help="Explicit newly qualified execution profile; does not activate it")
    parser.add_argument("--register", action="store_true")
    args = parser.parse_args()
    db = Database(Settings.from_env())
    try:
        header, result = verify(db, args.failed_audit, profile_id=args.profile_id)
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
