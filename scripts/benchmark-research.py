"""Run/collect an actual research loop in a separately provisioned Next clone."""

import argparse
import json
import multiprocessing
import time

from psycopg.conninfo import conninfo_to_dict

from dehps_next.artifacts import Artifacts
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest, now
from dehps_next.release import code_identity, numeric_identity
from dehps_next.research import Research
from dehps_next.research_compute import close_origin_pool
from dehps_next.research_memory import known_specs
from dehps_next.worker import Worker

NAME = "qwen-complete-loop"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "worker", "collect"])
    parser.add_argument("--role", choices=["compute", "planning"], default="compute")
    args = parser.parse_args()
    settings = Settings.from_env()
    assert conninfo_to_dict(settings.database_url)["dbname"].startswith("dehps_next_qwen_")
    assert settings.runtime.name.startswith("qwen-case-"), "Never run against the production runtime"
    db = Database(settings)
    artifacts = Artifacts(settings, db)
    if args.command == "prepare":
        assert not (settings.runtime / "benchmark-prepared.json").exists()
        with db.pool.connection() as c, c.transaction():
            c.execute("UPDATE research_programs SET state='DISABLED'")
            c.execute("UPDATE jobs SET state='SNAPSHOT_EXCLUDED' WHERE state IN ('READY','RUNNING')")
            c.execute("UPDATE resource_reservations SET state='SNAPSHOT_EXCLUDED' WHERE state='ACTIVE'")
        program = db.rows(
            "SELECT champion_spec,last_dataset FROM research_programs WHERE id='autonomous-v2'"
        )[0]
        memory = [digest(s) for s in known_specs(db, program["last_dataset"])]
        Research(db, artifacts).create(
            NAME,
            root_spec=program["champion_spec"],
            planner="local",
            max_nodes=8,
            topic={
                "name": "regularized-history",
                "methods": ["ridge", "fft", "newton"],
                "question": "Which representation and shrinkage survives recent and dispersed checks?",
            },
        )
        result = {
            "at": now().isoformat(),
            "code": code_identity(),
            "numeric": numeric_identity(),
            "root": program["champion_spec"],
            "known_recipe_digests": memory,
            "mail_attempts_before": db.rows("SELECT count(*) AS n FROM mail_attempts")[0]["n"],
        }
        (settings.runtime / "benchmark-prepared.json").write_text(json.dumps(result) + "\n")
    elif args.command == "worker":
        worker = Worker(db, artifacts, worker_id="benchmark-" + args.role, role=args.role)
        start = time.monotonic()
        try:
            while time.monotonic() - start < 480:
                campaign = db.rows("SELECT status FROM research_campaigns WHERE id=%s", (NAME,))[0]
                if campaign["status"] in ("BATCH_COMPLETE", "SEARCH_EXHAUSTED"):
                    break
                if campaign["status"].startswith("BLOCKED_"):
                    raise RuntimeError(campaign["status"])
                if not worker.once():
                    time.sleep(settings.poll_seconds)
            else:
                raise RuntimeError("BENCHMARK_WALL_LIMIT")
        finally:
            close_origin_pool()
            proof = {
                "at": now().isoformat(),
                "seconds": time.monotonic() - start,
                "no_fitter_children": not multiprocessing.active_children(),
            }
            (settings.runtime / f"benchmark-{args.role}.json").write_text(json.dumps(proof) + "\n")
    else:
        prepared = json.loads((settings.runtime / "benchmark-prepared.json").read_text())
        nodes = db.rows(
            "SELECT id,parent_id,path,spec,status,decision,hypothesis,evaluation->'execution' AS execution,evaluation->'business' AS business FROM research_nodes WHERE campaign_id=%s ORDER BY created_at,id",
            (NAME,),
        )
        calls = db.rows(
            "SELECT id,attempt_id,model,stage,state,metrics,created_at FROM research_model_calls WHERE campaign_id=%s ORDER BY id",
            (NAME,),
        )
        actions = db.rows(
            "SELECT action,evidence FROM research_decisions WHERE campaign_id=%s ORDER BY id", (NAME,)
        )
        spans = db.rows(
            """SELECT j.kind,r.created_at,r.ended_at,r.wall_seconds,r.process_cpu_seconds
            FROM resource_reservations r JOIN jobs j ON j.id=r.job_id JOIN research_nodes n ON n.id=j.research_node_id
            WHERE n.campaign_id=%s ORDER BY r.created_at""",
            (NAME,),
        )
        children = [n for n in nodes if n["parent_id"]]
        known = set(prepared["known_recipe_digests"])
        result = {
            "scope": "REAL_ISOLATED_APPLICATION_DEVELOPMENT_REPLAY;NOT_FORWARD_EVIDENCE",
            "code": code_identity(),
            "numeric": numeric_identity(),
            "campaign": db.rows(
                "SELECT status,config,protocol->>'digest' AS protocol_digest FROM research_campaigns WHERE id=%s",
                (NAME,),
            )[0],
            "nodes": nodes,
            "calls": calls,
            "actions": actions,
            "spans": spans,
            "registered_children": len(children),
            "evaluated_children": sum(n["execution"] is not None for n in children),
            "statistically_confirmed_hit_improvements": sum(
                n["status"] == "ACCEPT_IMPROVEMENT"
                and n["decision"].get("business", {}).get("statistically_confirmed", False)
                for n in children
            ),
            "novel_children_against_start": sum(digest(n["spec"]) not in known for n in children),
            "fresh_origin_fits": sum(
                (n["execution"] or {}).get("origin_fits_executed_this_attempt", 0) for n in nodes
            ),
            "gradient_steps": sum(
                (n["execution"] or {}).get("gradient_steps_executed_this_attempt", 0) for n in nodes
            ),
            "improvements": sum(n["status"] == "ACCEPT_IMPROVEMENT" for n in children),
            "failed_jobs": db.rows(
                "SELECT count(*) AS n FROM jobs j JOIN research_nodes n ON n.id=j.research_node_id WHERE n.campaign_id=%s AND j.state='FAILED'",
                (NAME,),
            )[0]["n"],
            "new_mail_attempts": db.rows("SELECT count(*) AS n FROM mail_attempts")[0]["n"]
            - prepared["mail_attempts_before"],
        }
        (settings.runtime / "benchmark-result.json").write_text(
            json.dumps(result, default=str, indent=2) + "\n"
        )
        print(
            json.dumps(
                {k: v for k, v in result.items() if k not in ("nodes", "calls", "actions", "spans")},
                default=str,
            )
        )
    db.close()


if __name__ == "__main__":
    main()
