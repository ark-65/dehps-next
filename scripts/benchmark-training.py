"""Compare predictor CPU threads with fixed real prior fits and optional full-GPU Qwen."""

import argparse
import copy
import hashlib
import json
import os
import re
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import torch

from dehps_next.artifacts import Artifacts
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.errors import DomainError
from dehps_next.model import vectors
from dehps_next.research_agent import request_json
from dehps_next.research_compute import fit_prior

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("command", choices=["freeze", "trial"])
parser.add_argument("--threads", type=int, choices=[8, 12, 16, 20], default=8)
parser.add_argument("--repeats", type=int, choices=[3, 10], default=3)
parser.add_argument("--label", default="trial")
parser.add_argument("--with-qwen", action="store_true")
parser.add_argument("--wall-seconds", type=int, default=210)
args = parser.parse_args()
assert 1 <= args.wall_seconds <= 300
assert re.fullmatch(r"[a-z0-9-]{1,40}", args.label)
root = Path.cwd() / "runtime" / "training-benchmark"
root.mkdir(exist_ok=True)
if args.command == "trial":
    assert not any(
        (root / f"{kind}-{args.label}.json").exists()
        for kind in ["attempt", "result", "progress", "receipts", "timeout"]
    ), "Use a new label; preserve every attempted trial and actual token receipt"
    attempt = root / f"attempt-{args.label}.json"
    attempt.write_text(
        json.dumps(
            {
                "at": datetime.now(UTC).isoformat(),
                "threads": args.threads,
                "with_qwen": args.with_qwen,
                "state": "STARTED",
            }
        )
        + "\n"
    )

    def deadline():
        state = result() if "result" in globals() else {"complete": False, "phase": "BEFORE_TIMED_FITS"}
        state["exit_reason"] = "BENCHMARK_WALL_LIMIT"
        (root / f"timeout-{args.label}.json").write_text(json.dumps(state) + "\n")
        os._exit(124)

    watchdog = threading.Timer(args.wall_seconds, deadline)
    watchdog.daemon = True
    watchdog.start()
s = Settings.from_env()
db = Database(s)
a = Artifacts(s, db)
if args.command == "freeze":
    assert not any(
        any(root.glob(f"{kind}-*.json")) for kind in ["attempt", "result", "progress", "receipts", "timeout"]
    )
    # Reuse the GPU comparison's bounded recipes/origins, so the only changed variable is threads.
    work = json.loads(Path("docs/acceptance/gpu-qwen-benchmark-20261030.json").read_text())["workload"]
    assert len(work["specs"]) == 3 and len(work["origins"]) <= 16
    requests = []
    for stage in ["HYPOTHESES", "TOOL_FEEDBACK_SELECTION"]:
        row = db.rows(
            "SELECT id,request FROM research_model_calls WHERE stage=%s AND state='SUCCEEDED' ORDER BY id DESC LIMIT1".replace(
                "LIMIT1", "LIMIT 1"
            ),
            (stage,),
        )[0]
        requests.append(
            {"source_call": row["id"], "stage": stage, "payload": json.loads(a.read(row["request"]))}
        )
    (root / "workload.json").write_text(json.dumps(work, indent=2) + "\n")
    (root / "requests.json").write_text(json.dumps(requests) + "\n")
    print(
        json.dumps(
            {
                "source_campaign": work["source_campaign"],
                "origins": len(work["origins"]),
                "specs": work["specs"],
                "request_sources": [{k: r[k] for k in ["source_call", "stage"]} for r in requests],
            }
        ),
        flush=True,
    )
    db.close()
    raise SystemExit(0)
work = json.loads((root / "workload.json").read_text())
row = db.rows(
    "SELECT ds.artifact FROM research_campaigns r JOIN datasets ds ON ds.id=r.dataset_id WHERE r.id=%s",
    (work["source_campaign"],),
)[0]
matrix = vectors(json.loads(a.read(row["artifact"]))["rows"])
assert len(matrix) == work["history_rows"]
torch.set_num_threads(args.threads)
assert torch.get_num_threads() == args.threads
receipts = []


def infer(payload, stage):
    receipt = {
        "at": datetime.now(UTC).isoformat(),
        "stage": stage,
        "model": payload["model"],
        "request_digest": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        "metrics": {},
    }
    receipts.append(receipt)
    target = root / f"receipts-{args.label}.json"
    target.write_text(json.dumps(receipts, indent=2) + "\n")
    started = time.monotonic()
    try:
        response = request_json("/api/chat", payload, timeout=180)
        receipt["metrics"] = {
            k: response.get(k)
            for k in [
                "prompt_eval_count",
                "eval_count",
                "eval_duration",
                "prompt_eval_duration",
                "load_duration",
                "done_reason",
            ]
        }
    finally:
        receipt["seconds"] = time.monotonic() - started
        target.write_text(json.dumps(receipts, indent=2) + "\n")
    assert response.get("done") and response.get("done_reason") != "length"
    if "format" in payload:
        assert set(payload["format"]["required"]) <= set(json.loads(response["message"]["content"]))


ps = None
if args.with_qwen:
    request_json("/api/generate", {"model": "qwen3:1.7b", "keep_alive": 0})
    infer(
        {
            "model": "qwen3:1.7b",
            "stream": False,
            "think": False,
            "keep_alive": "5m",
            "messages": [{"role": "user", "content": "Reply only OK. /no_think"}],
            "options": {"num_thread": 4, "num_ctx": 4096, "num_predict": 8, "temperature": 0, "seed": 1729},
        },
        "warmup",
    )
    ps = request_json("/api/ps")
    loaded = next((m for m in ps.get("models", []) if m.get("name") == "qwen3:1.7b"), {})
    assert loaded.get("size", 0) > 0 and loaded.get("size_vram", 0) >= loaded["size"], ps
fit_prior(matrix[: work["origins"][0]], work["specs"][0], 1729 + work["origins"][0], lambda: None)
errors = []


def inference_pair():
    try:
        for row in json.loads((root / "requests.json").read_text()):
            payload = copy.deepcopy(row["payload"])
            payload["options"]["num_thread"] = 4
            payload["keep_alive"] = "5m"
            infer(payload, row["stage"])
    except (DomainError, OSError, ValueError, AssertionError, KeyError) as exc:
        errors.append(repr(exc))


start = time.monotonic()
started_at = datetime.now(UTC).isoformat()
cpu = time.process_time()
thread = threading.Thread(target=inference_pair) if args.with_qwen else None
if thread:
    thread.start()
fits = steps = 0
predictions = []
expected = len(work["specs"]) * len(work["origins"]) * args.repeats


def result(complete=False):
    return {
        "label": args.label,
        "started_at": started_at,
        "threads": args.threads,
        "with_qwen": args.with_qwen,
        "repeats": args.repeats,
        "expected_fits": expected,
        "completed_fits": fits,
        "gradient_steps": steps,
        "complete": complete,
        "seconds": time.monotonic() - start,
        "process_cpu_seconds": time.process_time() - cpu,
        "affinity": sorted(os.sched_getaffinity(0)),
        "errors": errors,
        "scope": "REPEATED_REAL_PRIOR_FITS_NOT_INDEPENDENT_DRAW_EVIDENCE",
    }


progress = root / f"progress-{args.label}.json"
progress.write_text(json.dumps(result()) + "\n")
for spec in work["specs"]:
    for origin in work["origins"] * args.repeats:
        red, blue, trained = fit_prior(matrix[:origin], spec, 1729 + origin, lambda: None)
        assert trained["weight_digest"] != trained["initial_weight_digest"]
        fits += 1
        steps += trained["gradient_steps"]
        predictions.append(np.concatenate([red, blue]))
        if fits % 5 == 0:
            progress.write_text(json.dumps(result()) + "\n")
train_seconds = time.monotonic() - start
if thread:
    thread.join()
r = result(not errors)
r["training_complete"] = fits == expected
r.update(
    {
        "training_seconds": train_seconds,
        "active_training_fits_per_second": fits / train_seconds,
        "planning_seconds": sum(c["seconds"] for c in receipts if c["stage"] != "warmup"),
        "whole_block_fits_per_second": fits / r["seconds"],
        "prediction_digest": hashlib.sha256(np.asarray(predictions).tobytes()).hexdigest(),
        "gpu_residency": ps,
    }
)
np.save(root / f"predictions-{args.label}.npy", np.asarray(predictions))
(root / f"result-{args.label}.json").write_text(json.dumps(r, indent=2) + "\n")
attempt.write_text(json.dumps({"state": "FAILED" if errors else "COMPLETE", "threads": args.threads}) + "\n")
print(json.dumps(r), flush=True)
db.close()
assert not errors, errors
