"""Measure real independent-origin fits in an isolated Next clone; never writes production."""

import argparse
import json
import re
import time
from pathlib import Path

import torch
from psycopg.conninfo import conninfo_to_dict

from dehps_next.artifacts import Artifacts
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.domain import digest
from dehps_next.errors import DomainError
from dehps_next.release import code_identity, numeric_identity
from dehps_next.research_compute import close_origin_pool, compute_node
from dehps_next.research_protocol import make_protocol
from dehps_next.training_window import status as training_window


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", required=True)
    parser.add_argument("--processes", type=int, choices=[1, 2, 4, 8], required=True)
    parser.add_argument("--threads", type=int, choices=[1, 2, 4, 8], required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    settings = Settings.from_env()
    assert conninfo_to_dict(settings.database_url)["dbname"].startswith("dehps_next_parallel_")
    assert settings.runtime.name.startswith("parallel-"), "Use an isolated runtime clone"
    assert re.fullmatch(r"[a-z0-9-]{1,40}", args.label)
    output = settings.runtime.parent / "parallel-benchmark" / f"operator-{args.label}.json"
    output.parent.mkdir(exist_ok=True)
    assert not output.exists(), "Preserve prior attempts; choose a new label"
    torch.set_num_threads(args.threads)
    db = Database(settings)
    artifacts = Artifacts(settings, db)
    started = time.monotonic()

    def cpu():
        values = dict(line.split() for line in Path("/sys/fs/cgroup/cpu.stat").read_text().splitlines())
        return int(values["usage_usec"]) / 1e6

    def pulse():
        if time.monotonic() - started > 300:
            raise DomainError("BENCHMARK_WALL_LIMIT", "Five-minute total budget exhausted")
        with db.pool.connection() as c:
            if training_window(c)["paused"]:
                raise DomainError("YIELD_DRAW_PAUSE", "Benchmark respects the real draw pause")

    result = {
        "scope": "COMPUTE_SCREEN_ONLY;NOT_WHOLE_LEARNING_LOOP_OR_FORWARD_EVIDENCE",
        "code_identity": code_identity(),
        "numeric_identity": numeric_identity(),
        "campaign": args.campaign,
        "processes": args.processes,
        "threads_per_origin": args.threads,
        "nodes": [],
        "state": "STARTED",
    }
    output.write_text(json.dumps(result, indent=2) + "\n")
    cpu_start = cpu()
    try:
        record = db.rows(
            "SELECT ds.artifact FROM research_campaigns r JOIN datasets ds ON ds.id=r.dataset_id WHERE r.id=%s",
            (args.campaign,),
        )[0]
        snapshot = json.loads(artifacts.read(record["artifact"]))
        protocol = make_protocol(len(snapshot["rows"]), 100, 200)
        specs = db.rows(
            "SELECT spec FROM research_nodes WHERE campaign_id=%s ORDER BY created_at,id LIMIT 3",
            (args.campaign,),
        )
        assert len(specs) == 3, "Choose a completed three-direction campaign"
        result["protocol_digest"] = protocol["digest"]
        for row in specs:
            pulse()
            scored, _, _, execution = compute_node(
                snapshot,
                row["spec"],
                protocol,
                pulse,
                lambda _: None,
                processes=args.processes,
                threads=args.threads,
                seconds=150,
            )
            result["nodes"].append(
                {
                    "spec": row["spec"],
                    "execution": execution,
                    "row_count": len(scored),
                    "score_digest": digest(scored),
                }
            )
        result["state"] = "COMPLETE"
    except Exception as exc:
        result.update(state="FAILED", error=getattr(exc, "code", type(exc).__name__))
        raise
    finally:
        result.update(
            seconds=time.monotonic() - started,
            cpu_seconds=cpu() - cpu_start,
            cpu_scope="CONTAINER_INCLUDING_LIVE_FITTERS",
        )
        output.write_text(json.dumps(result, indent=2) + "\n")
        close_origin_pool()
        db.close()
    print(json.dumps(result))


if __name__ == "__main__":
    main()
