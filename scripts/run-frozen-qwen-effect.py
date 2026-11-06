"""Spawn-safe execution of the approved frozen comparison; no work runs on import."""

import argparse
import importlib.util
import json
import time
from decimal import Decimal
from pathlib import Path


class IntegralProgressCounts:
    """Expose PostgreSQL numeric SUM(bigint) counters as exact JSON integers."""

    def __init__(self, database):
        self.database = database

    def __getattr__(self, name):
        return getattr(self.database, name)

    def rows(self, query, params=()):
        rows = self.database.rows(query, params)
        if "FIT_PROGRESS" in query and len(rows) == 1 and set(rows[0]) == {"origins", "steps"}:
            row = dict(rows[0])
            for key, value in row.items():
                if isinstance(value, Decimal):
                    if not value.is_finite() or value != value.to_integral_value():
                        raise ValueError("Training progress counters must be finite integers")
                    row[key] = int(value)
                elif type(value) is not int:
                    raise TypeError("Unexpected training progress counter type")
                if row[key] < 0:
                    raise ValueError("Training progress counters must be nonnegative")
            return [row]
        return rows


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    from dehps_next.artifacts import Artifacts
    from dehps_next.config import Settings
    from dehps_next.db import Database
    from dehps_next.research_compute import close_origin_pool
    from dehps_next.research_selection_evidence import SEMANTIC_FAILURES

    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("prepare", "choose", "evaluate", "collect"))
    args = parser.parse_args()
    operation = Path("/operation")
    drivers = Path("/app/frozen-drivers")
    effect = load("frozen_effect", drivers / "benchmark-selection-effect.py")
    admission = load("admission", drivers / "qwen-acceptance-admission.py")
    feedback = load("current_feedback", drivers / "frozen-current-feedback.py")
    settings = Settings.from_env()
    db = Database(settings)
    artifacts = Artifacts(settings, db)
    assert db.rows("SELECT current_database() AS n")[0]["n"] == "dehps_next_qwen4_grounded_acceptance"
    assert settings.runtime.name == "grounded-case"
    result = json.loads((operation / "mechanism-result.json").read_text())
    frozen = json.loads((operation / "frozen-run.json").read_text())
    assert result["passed"] and result["result"]["study"] == frozen["mechanism"]
    study = frozen["effect"]
    original = effect.mechanism.recoverable_review

    def actual(*positional, **keywords):
        while True:
            admission.wait(db, operation / "admission.json", operation / "admission-events.jsonl")
            reply = original(*positional, **keywords)
            if reply["valid"] or reply.get("error") in SEMANTIC_FAILURES:
                return reply
            print(json.dumps({"physical_void_retry": reply, "logical_choice_recorded": False}), flush=True)
            time.sleep(15)

    effect.mechanism.recoverable_review = actual
    original_feedback = effect.cross_round_feedback

    def comparable_feedback(database, campaign, parent):
        memory = original_feedback(database, campaign, parent)
        if memory["evidence"] and memory["trials"]:
            return memory
        return feedback.current_feedback(database, artifacts, effect, campaign, parent)

    effect.cross_round_feedback = comparable_feedback
    try:
        if args.phase == "prepare":
            with db.pool.connection() as connection, connection.transaction():
                assert not connection.execute("""SELECT 1 FROM jobs WHERE kind='RESEARCH_PLAN'
                    AND state='RUNNING' AND lease_until>now()""").fetchone()
                connection.execute("""UPDATE jobs SET state='SNAPSHOT_EXCLUDED'
                    WHERE kind='RESEARCH_PLAN' AND state IN ('READY','RUNNING')""")
            effect.prepare(db, artifacts, study, frozen["mechanism"])
        elif args.phase == "collect":
            effect.collect(IntegralProgressCounts(db), artifacts, study)
        else:
            getattr(effect, args.phase)(db, artifacts, study)
        if args.phase == "collect":
            payload = db.rows("SELECT payload FROM research_review_results WHERE study_id=%s", (study,))[0][
                "payload"
            ]
            (operation / "effect-result.json").write_text(json.dumps(payload, indent=2) + "\n")
        print(json.dumps({"phase": args.phase, "state": "COMPLETE", "study": study}), flush=True)
    finally:
        close_origin_pool()
        db.close()


if __name__ == "__main__":
    main()
