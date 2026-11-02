"""Restart-safe follow-up of the frozen local mechanism, then the fixed24-pool study."""

import argparse
import copy
import hashlib
import importlib.util
import json
import time
from pathlib import Path

from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

from dehps_next.artifacts import Artifacts
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest
from dehps_next.release import code_identity
from dehps_next.research_agent import request_json
from dehps_next.research_compute import close_origin_pool
from dehps_next.research_selection import mechanism_metrics
from dehps_next.research_selection_evidence import SEMANTIC_FAILURES


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


mechanism = module("followup_mechanism", "benchmark-selection.py")
effect = module("followup_effect", "benchmark-selection-effect.py")
ORDER = [(model, think) for model in ("qwen3:1.7b", "qwen3:4b", "qwen3:8b") for think in (False, True)]


def source_profiles(db, corpus):
    rows = db.rows(
        """SELECT s.id,s.protocol,r.payload AS result FROM research_review_studies s
        LEFT JOIN research_review_results r ON r.study_id=s.id
        WHERE s.protocol->>'kind'='MECHANISM_PROFILE_V4' AND s.protocol->>'corpus'=%s""",
        (corpus,),
    )
    result = {}
    for row in rows:
        p = row["protocol"]["profile"]
        key = (p["model"], p["think"])
        if p["selector_contract"] != "comparative-v4.4" or key in result:
            raise RuntimeError("A unique frozen v4.4 configuration per approved model/mode is required")
        result[key] = row
    return result


def continuation(db, artifacts, corpus, sources):
    """Carry every performed answer, retry only physical voids, then continue the model order."""
    newcorpus = corpus + "-continued"
    if len(newcorpus) > 60:
        raise RuntimeError("Recovery corpus identity exceeds its bound")
    old = db.rows("SELECT protocol,sha256 FROM research_review_studies WHERE id=%s", (corpus,))[0]
    header = {
        **old["protocol"],
        "driver_sha256": hashlib.sha256(Path(mechanism.__file__).read_bytes()).hexdigest(),
        "controller_source": code_identity(),
        "recovery_of": corpus,
        "source_corpus_sha256": old["sha256"],
        "recovery_policy": "CARRY_ALL_PERFORMED_CHOICES_INCLUDING_WRONG;RETRY_ONLY_INFRASTRUCTURE;SAME_INPUT_SEED",
    }
    pairs = db.rows("SELECT * FROM research_review_pairs WHERE study_id=%s ORDER BY pair", (corpus,))
    assert len(pairs) == 12 and all(digest(p["basis"]) == p["sha256"] for p in pairs)
    with db.pool.connection() as c, c.transaction():
        c.execute(
            "INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
            (newcorpus, Jsonb(header), digest(header)),
        )
        if c.execute("SELECT sha256 FROM research_review_studies WHERE id=%s", (newcorpus,)).fetchone()[
            "sha256"
        ] != digest(header):
            raise RuntimeError("Use the frozen recovery source and driver")
        for p in pairs:
            c.execute(
                "INSERT INTO research_review_pairs(study_id,pair,basis,sha256) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (newcorpus, p["pair"], Jsonb(p["basis"]), p["sha256"]),
            )
    mechanism.CORPUS, mechanism.CONTEXT = newcorpus, corpus + "-context"
    inventory = {r["name"]: r["digest"] for r in request_json("/api/tags")["models"]}
    for model, think in ORDER:
        previous = sources.get((model, think))
        config = (
            previous["protocol"]["profile"] if previous else mechanism.profile(model, think, inventory[model])
        )
        if inventory[model] != config["model_digest"]:
            raise RuntimeError("The frozen model digest changed")
        identity = digest(config)
        study = "qwen-mechanism-" + digest([newcorpus, identity])[:16]
        protocol = {
            "kind": "MECHANISM_PROFILE_V4",
            "profile": config,
            "profile_id": identity,
            "corpus": newcorpus,
            "context_campaign": corpus + "-context",
            "corpus_sha": digest(header),
            "futility": header["futility"],
            "scope": "NO_NEW_FITS",
        }
        with db.pool.connection() as c, c.transaction():
            c.execute(
                "INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                (study, Jsonb(protocol), digest(protocol)),
            )
            for p in pairs:
                c.execute(
                    "INSERT INTO research_review_pairs(study_id,pair,basis,sha256) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (study, p["pair"], Jsonb(p["basis"]), p["sha256"]),
                )
            if previous:
                for r in c.execute(
                    "SELECT * FROM research_review_selections WHERE study_id=%s", (previous["id"],)
                ).fetchall():
                    payload = r["payload"]
                    if not payload["valid"] and payload.get("error") not in SEMANTIC_FAILURES:
                        continue
                    carried = {
                        **copy.deepcopy(payload),
                        "recovery_source": {
                            "study_id": previous["id"],
                            "pair": r["pair"],
                            "arm": r["arm"],
                            "original_payload_sha256": digest(payload),
                            "scope": "ACTUAL_CARRIED_CHOICE;NOT_NEW_CALL_OR_FIT",
                        },
                    }
                    c.execute(
                        "INSERT INTO research_review_selections(study_id,pair,arm,payload,created_at) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (study, r["pair"], r["arm"], Jsonb(carried), r["created_at"]),
                    )
        result = mechanism.run_profile(db, artifacts, header, config)
        if result["passed"]:
            return study
    return None


def ready(db, corpus):
    profiles = source_profiles(db, corpus)
    for key in ORDER:
        row = profiles.get(key)
        if not row or row["result"] is None:
            return "WAITING", profiles, None
        if row["result"]["passed"]:
            return "PASSED", profiles, row
    return "NO_PROFILE_PASSED", profiles, None


def run(db, artifacts, corpus, study):
    state, profiles, chosen = ready(db, corpus)
    if state == "WAITING":
        return {"state": state, "corpus": corpus}
    invalid = db.rows(
        "SELECT payload FROM research_review_selections WHERE study_id=ANY(%s) AND NOT (payload->>'valid')::boolean",
        ([row["id"] for row in profiles.values()],),
    )
    if any(r["payload"].get("error") not in SEMANTIC_FAILURES for r in invalid):
        mechanism_study = continuation(db, artifacts, corpus, profiles)
        if not mechanism_study:
            return {"state": "NO_RECOVERED_PROFILE_PASSED", "effect_study_started": False}
    elif state == "NO_PROFILE_PASSED":
        return {
            "state": state,
            "effect_study_started": False,
            "scope": "NO_QWEN_BENEFIT_CLAIM;PRIMARY_FALLBACK_UNCHANGED",
        }
    else:
        mechanism_study = chosen["id"]
    completed = db.rows("SELECT payload FROM research_review_results WHERE study_id=%s", (mechanism_study,))[
        0
    ]["payload"]
    actual = mechanism_metrics(db, mechanism_study, completed["profile"])
    if any(abs(actual[k] - completed[k]) > 1e-12 for k in actual):
        raise RuntimeError("Stored mechanism result differs from its real immutable slots")
    effect.prepare(db, artifacts, study, mechanism_study)
    count = db.rows("SELECT count(*) AS n FROM research_review_selections WHERE study_id=%s", (study,))[0][
        "n"
    ]
    if count < 48:
        effect.choose(db, artifacts, study)
    if not db.rows("SELECT 1 FROM research_review_results WHERE study_id=%s", (study,)):
        effect.evaluate(db, artifacts, study)
        effect.collect(db, artifacts, study)
    return {
        "state": "EFFECT_COMPLETE",
        "mechanism_study": mechanism_study,
        "effect_study": study,
        "primary_profile_activation": False,
        "scope": "REVIEW_ACTUAL_RESULT_BEFORE_LIVE_MODEL_SWITCH",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--study", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    settings = Settings.from_env()
    if (
        conninfo_to_dict(settings.database_url).get("dbname") != "dehps_next_parent_acceptance"
        or settings.runtime.name != "parent-case"
    ):
        raise SystemExit("Only the named isolated Next acceptance database/runtime is allowed")
    if not 1 <= len(args.study) <= 50 or not 1 <= len(args.corpus) <= 50:
        raise SystemExit("Use bounded fixed study identities")
    db = Database(settings)
    artifacts = Artifacts(settings, db)
    workflow = args.study + "-workflow"
    header = {
        "kind": "SELECTION_ACCEPTANCE_WORKFLOW_V1",
        "corpus": args.corpus,
        "study": args.study,
        "source": code_identity(),
        "drivers": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (Path(__file__), Path(mechanism.__file__), Path(effect.__file__))
        },
        "model_order": ORDER,
        "primary_activation": False,
        "scope": "LOCAL_HISTORICAL_ACCEPTANCE;NO_SMTP_OR_PRIMARY_EXECUTION",
    }
    try:
        with db.pool.connection() as c, c.transaction():
            c.execute(
                "INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
                (workflow, Jsonb(header), digest(header)),
            )
            assert c.execute(
                "SELECT sha256 FROM research_review_studies WHERE id=%s", (workflow,)
            ).fetchone()["sha256"] == digest(header)
        while True:
            previous = db.rows("SELECT payload FROM research_review_results WHERE study_id=%s", (workflow,))
            if previous:
                print(json.dumps(previous[0]["payload"]), flush=True)
                return
            result = run(db, artifacts, args.corpus, args.study)
            print(json.dumps(result), flush=True)
            if result["state"] != "WAITING":
                with db.pool.connection() as c:
                    c.execute(
                        "INSERT INTO research_review_results(study_id,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                        (workflow, Jsonb(result)),
                    )
                return
            if args.once:
                return
            time.sleep(60)
    finally:
        close_origin_pool()
        db.close()


if __name__ == "__main__":
    main()
