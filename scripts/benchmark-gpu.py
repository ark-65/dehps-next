"""Bounded fixed-workload CPU/Vulkan comparison; actual prior fits, no publication."""

import argparse
import copy
import datetime
import hashlib
import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path

import torch

from dehps_next.artifacts import Artifacts
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.model import vectors
from dehps_next.research_compute import fit_prior

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("command", choices=["freeze", "trial"])
parser.add_argument("--backend", choices=["cpu", "gpu"], default="cpu")
parser.add_argument("--label", default="trial")
parser.add_argument("--profile", choices=["serial", "concurrent"], default="concurrent")
parser.add_argument("--qwen-threads", type=int, default=4)
args = parser.parse_args()
assert re.fullmatch(r"[a-z0-9-]{1,40}", args.label), "bounded filename label required"
assert 1 <= args.qwen_threads <= (4 if args.backend == "gpu" else 20)
root = Path.cwd() / "runtime" / "gpu-benchmark"
root.mkdir(parents=True, exist_ok=True)
mode, trial, profile, threads = args.backend, args.label, args.profile, args.qwen_threads
if args.command == "freeze":
    assert not any(root.glob("receipts-*.json")), (
        "Import prior receipts and clean owned benchmark runtime before freezing again"
    )
else:
    assert not any((root / f"{kind}-{trial}.json").exists() for kind in ["receipts", "result", "ps"]), (
        "Use a fresh trial label; never overwrite actual token receipts"
    )
# These isolated local aliases are intentional; production endpoint policy is unchanged.
base = {"cpu": "http://next-inference:11434", "gpu": "http://next-gpu-bench:11434"}[mode]
receipts = []
# Kill the read-only benchmark process if an HTTP/driver call stops making progress.
watchdog = threading.Timer(440, lambda: os._exit(124))
watchdog.daemon = True
watchdog.start()


def request(path, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(base + path, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as r:
        body = r.read(128 * 1024 + 1)
        assert len(body) <= 128 * 1024, "response byte limit"
        return json.loads(body)


def validate(value, schema):
    kind = schema.get("type")
    if kind == "object":
        assert isinstance(value, dict)
        assert set(schema.get("required", [])) <= set(value)
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            assert set(value) <= set(properties)
        for key, item in value.items():
            if key in properties:
                validate(item, properties[key])
    elif kind == "string":
        assert isinstance(value, str)
        assert schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 100000)
    elif kind == "integer":
        assert type(value) is int
    elif kind == "number":
        assert type(value) in (int, float)
    if "enum" in schema:
        assert value in schema["enum"]


def call(payload, stage):
    at = datetime.datetime.now(datetime.UTC).isoformat()
    start = time.monotonic()
    row = {
        "at": at,
        "stage": stage,
        "model": payload["model"],
        "request_digest": hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest(),
        "metrics": {},
    }
    try:
        r = request("/api/chat", payload)
        row["metrics"] = {
            k: r.get(k)
            for k in [
                "prompt_eval_count",
                "eval_count",
                "eval_duration",
                "prompt_eval_duration",
                "load_duration",
                "total_duration",
                "done_reason",
            ]
        }
    finally:
        row["seconds"] = time.monotonic() - start
        receipts.append(row)
        (root / f"receipts-{trial}.json").write_text(json.dumps(receipts, indent=2) + "\n")
    assert r.get("done") and r.get("done_reason") != "length", row
    if "format" in payload:
        value = json.loads(r["message"]["content"])
        validate(value, payload["format"])
    return r


s = Settings.from_env()
db = Database(s)
a = Artifacts(s, db)
if args.command == "freeze":
    campaign = db.rows(
        "SELECT r.id,r.protocol,ds.artifact FROM research_campaigns r JOIN datasets ds ON ds.id=r.dataset_id WHERE r.program_id='autonomous-v2' ORDER BY r.created_at DESC LIMIT 1"
    )[0]
    matrix = vectors(json.loads(a.read(campaign["artifact"]))["rows"])
    rows = db.rows(
        "SELECT DISTINCT ON (n.spec->>'method') n.spec FROM research_nodes n JOIN research_campaigns r ON r.id=n.campaign_id WHERE r.program_id='autonomous-v2' AND n.evaluation IS NOT NULL AND n.spec->>'method' IN ('fft','ridge','newton') ORDER BY n.spec->>'method',n.completed_at DESC"
    )
    assert len(rows) == 3
    origins = campaign["protocol"]["origins"]
    chosen = sorted(set(origins[-8:] + [origins[round(i * (len(origins) - 1) / 7)] for i in range(8)]))
    work = {
        "source_campaign": campaign["id"],
        "specs": [r["spec"] for r in rows],
        "origins": chosen,
        "history_rows": len(matrix),
        "claim": "REPEATED_REAL_PRIOR_FITS_NOT_INDEPENDENT_DRAW_EVIDENCE",
    }
    records = []
    for stage in ["HYPOTHESES", "TOOL_FEEDBACK_SELECTION"]:
        row = db.rows(
            "SELECT id,request FROM research_model_calls WHERE stage=%s AND state='SUCCEEDED' ORDER BY id DESC LIMIT 1",
            (stage,),
        )[0]
        records.append(
            {"source_call": row["id"], "stage": stage, "payload": json.loads(a.read(row["request"]))}
        )
    # Requests stay in ignored Next runtime, never Git. No model/data publication or DB writes.
    (root / "workload.json").write_text(json.dumps(work, indent=2) + "\n")
    (root / "frozen-requests.json").write_text(json.dumps(records) + "\n")
    print(json.dumps(work))
    db.close()
    raise SystemExit(0)
work = json.loads((root / "workload.json").read_text())
records = json.loads((root / "frozen-requests.json").read_text())
x = db.rows(
    "SELECT ds.artifact FROM research_campaigns r JOIN datasets ds ON ds.id=r.dataset_id WHERE r.id=%s",
    (work["source_campaign"],),
)[0]
matrix = vectors(json.loads(a.read(x["artifact"]))["rows"])
assert s.training_threads == 8, "fixed training contract required"
torch.set_num_threads(8)
request("/api/generate", {"model": "qwen3:1.7b", "keep_alive": 0})
call(
    {
        "model": "qwen3:1.7b",
        "stream": False,
        "think": False,
        "keep_alive": "5m",
        "messages": [{"role": "user", "content": "Reply only OK. /no_think"}],
        "options": {"num_thread": threads, "num_ctx": 4096, "num_predict": 8, "temperature": 0, "seed": 1729},
    },
    "warmup",
)
ps = request("/api/ps")
loaded = next((m for m in ps.get("models", []) if m.get("name") == "qwen3:1.7b"), {})
if mode == "gpu":
    assert loaded.get("size", 0) > 0 and loaded.get("size_vram", 0) >= loaded["size"], ps
else:
    assert loaded.get("size_vram") == 0, "CPU baseline alias must resolve to an actual CPU provider"
(root / f"ps-{trial}.json").write_text(json.dumps(ps, indent=2) + "\n")
fit_prior(matrix[: work["origins"][0]], work["specs"][0], 1729 + work["origins"][0], lambda: None)
errors = []


def inference():
    try:
        for item in records:
            p = copy.deepcopy(item["payload"])
            p["options"]["num_thread"] = threads
            p["keep_alive"] = "5m"
            call(p, item["stage"])
    except (OSError, ValueError, AssertionError, KeyError) as e:
        errors.append(repr(e))


start = time.monotonic()
thread = threading.Thread(target=inference)
thread.start()
fits = steps = 0
fingerprint = hashlib.sha256()
if profile == "serial":
    thread.join()
train_start = time.monotonic()
for spec in work["specs"]:
    for origin in work["origins"] * 10:
        red, blue, trained = fit_prior(matrix[:origin], spec, 1729 + origin, lambda: None)
        assert trained["weight_digest"] != trained["initial_weight_digest"]
        fits += 1
        steps += trained["gradient_steps"]
        fingerprint.update(red.tobytes())
        fingerprint.update(blue.tobytes())
        assert time.monotonic() - start < 300, "trial wall deadline"
train_seconds = time.monotonic() - train_start
thread.join()
result = {
    "trial": trial,
    "mode": mode,
    "profile": profile,
    "training_threads": 8,
    "qwen_threads": threads,
    "affinity": sorted(os.sched_getaffinity(0)),
    "fits": fits,
    "gradient_steps": steps,
    "training_seconds": train_seconds,
    "fits_per_second": fits / train_seconds,
    "planning_seconds": sum(r["seconds"] for r in receipts if r["stage"] != "warmup"),
    "cycle_seconds": time.monotonic() - start,
    "probability_digest": fingerprint.hexdigest(),
    "errors": errors,
    "warmup_seconds": receipts[0]["seconds"],
    "gpu_offload_bytes": ps["models"][0].get("size_vram", 0),
    "scope": "FIXED_HISTORY_AND_REQUEST_REPLAY_NOT_FORWARD_EVIDENCE",
}
(root / f"result-{trial}.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result), flush=True)
db.close()
assert not errors, errors
