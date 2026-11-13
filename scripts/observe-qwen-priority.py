"""Publish conservative admission observations independently of slow reporting."""

import argparse
import fcntl
import hashlib
import json
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ("dehps-next-p0p1-worker-1", "dehps-next-p0p1-planner-1", "dehps-next-p0p1-steward-1")
WINDOW = """import json
from dehps_next.config import Settings
from dehps_next.db import Database
from dehps_next.training_window import status
d=Database(Settings.from_env())
try:
 with d.pool.connection() as c, c.transaction():
  c.execute('SET TRANSACTION READ ONLY')
  c.execute('SET LOCAL statement_timeout=8000')
  print(json.dumps(status(c)))
finally:
 d.close()
"""


def run(args, *, timeout=12, **kwargs):
    return subprocess.run(args, check=True, capture_output=True, text=True,
                          timeout=timeout, **kwargs).stdout.strip()


def host():
    memory = Path("/proc/meminfo").read_text()
    pressure = Path("/proc/pressure/memory").read_text()
    try:
        reply = run(["gdbus", "call", "--session", "--dest", "org.gnome.Mutter.IdleMonitor",
                     "--object-path", "/org/gnome/Mutter/IdleMonitor/Core", "--method",
                     "org.gnome.Mutter.IdleMonitor.GetIdletime"], timeout=5)
        idle = int(re.fullmatch(r"\(uint64 (\d+),\)", reply)[1]) / 1000
    except (subprocess.SubprocessError, TypeError, ValueError):
        idle = None  # Existing admission retains the original spacing when idle is unknown.
    return {"memory_available_bytes": int(re.search(r"MemAvailable:\s+(\d+)", memory)[1]) * 1024,
            "memory_full_avg10": float(re.search(r"full avg10=([\d.]+)", pressure)[1]),
            "desktop_idle_seconds": idle}


def running():
    return run(["docker", "inspect", "--format", "{{.State.Running}}", *PRIMARY], timeout=8
               ).splitlines() == ["true"] * len(PRIMARY)


def database(soak):
    query = """SELECT json_build_object(
      'db_observed_at',extract(epoch FROM now()),
      'latest_completed_at',(SELECT max(completed_at) FROM research_nodes),
      'fresh_training_workers',(SELECT count(*) FROM worker_status WHERE
        heartbeat_at>now()-interval '45 seconds' AND state IN ('RUNNING','IDLE')),
      'primary_next_call_at',CASE WHEN last_scheduled_at IS NOT NULL THEN extract(epoch FROM greatest(
        last_scheduled_at+interval '1800 seconds',
        CASE WHEN coalesce(reason,'')<>'' THEN retry_after END)) END,
      'primary_nominal_call_at',extract(epoch FROM last_scheduled_at+interval '1800 seconds'),
      'primary_cooldown_not_before',CASE WHEN coalesce(reason,'')<>'' THEN extract(epoch FROM retry_after) END,
      'primary_active_calls',(SELECT count(*) FROM research_model_calls WHERE state='RESERVED'
        AND stage LIKE 'CANDIDATE_SELECTION_V4_%'),
      'program',(SELECT json_build_object('generation',generation,'state',state)
        FROM research_programs WHERE id='autonomous-v2'),
      'soak',(SELECT to_jsonb(s) FROM research_soaks s WHERE id='__SOAK__'))
      FROM qwen_selection_state WHERE id=1""".replace("__SOAK__", soak)
    return json.loads(run(["docker", "exec", "-e",
                           "PGOPTIONS=-c default_transaction_read_only=on -c statement_timeout=8000",
                           "dehps-next-p0p1-database-1", "psql", "-X", "-At", "-U", "dehps_next",
                           "-d", "dehps_next", "-v", "ON_ERROR_STOP=1", "-c", query]))


def window():
    return json.loads(run(["docker", "exec", "-i", "dehps-next-p0p1-worker-1", "python", "-"],
                          input=WINDOW))


def observe(pool, soak):
    # Timestamp BEFORE every independent read. Publication time never freshens old observations.
    started = time.time()
    futures = {"host": pool.submit(host), "running": pool.submit(running),
               "database": pool.submit(database, soak), "window": pool.submit(window)}
    values, errors = {}, []
    for name, future in futures.items():
        try:
            values[name] = future.result()
        except (OSError, subprocess.SubprocessError, ValueError, TypeError, KeyError) as exc:
            errors.append({"component": name, "error": type(exc).__name__})
    if errors:
        raise RuntimeError(json.dumps(errors))
    ended = time.time()
    if not 0 <= ended - started <= 30:
        raise RuntimeError("Snapshot already exceeds original30-second freshness; do not publish")
    db, draw = values["database"], values["window"]
    if not db.get("program") or not db.get("soak") or type(draw.get("paused")) is not bool:
        raise RuntimeError("Missing source state; keep previous observation and fail closed")
    completed = db["latest_completed_at"]
    if not completed or type(db.get("primary_next_call_at")) not in (int, float):
        raise RuntimeError("Missing genuine training progress or production cadence")
    return {**values["host"], "observed_at": started, "published_at": ended,
            "capture_seconds": ended - started, "primary_running": values["running"],
            "training_progress_age_seconds": ended - datetime.fromisoformat(completed).timestamp(),
            "latest_completed_at": completed, "fresh_training_workers": db["fresh_training_workers"],
            "primary_next_call_headroom_seconds": db["primary_next_call_at"] - ended,
            "primary_next_call_not_before": db["primary_next_call_at"],
            "primary_nominal_call_not_before": db["primary_nominal_call_at"],
            "primary_cooldown_not_before": db["primary_cooldown_not_before"],
            "primary_active_calls": db["primary_active_calls"], "primary_draw_paused": draw["paused"],
            "window": draw, "program": db["program"], "soak": db["soak"],
            "observer": "QWEN_PRIORITY_READ_ONLY_V3", "reporting_in_critical_path": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation", required=True, type=Path)
    parser.add_argument("--soak", required=True)
    parser.add_argument("--interval", type=int, choices=(5, 10), default=10)
    parser.add_argument("--keep-running", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    op = args.operation.resolve()
    if op.parent != ROOT / "runtime/operations" or not op.is_dir():
        raise SystemExit("Use an existing direct Next operation directory")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", args.soak):
        raise SystemExit("Use the exact bounded Next soak identity")
    lock = (op / "priority-observer-v3.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    source = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with ThreadPoolExecutor(max_workers=4) as pool:
        while True:
            start = time.monotonic()
            try:
                sample = {**observe(pool, args.soak), "observer_source_sha256": source}
                pending = op / "admission-v3.pending"
                pending.write_text(json.dumps(sample) + "\n")
                pending.replace(op / "admission.json")
                capture = op / "priority-observations-v3.jsonl"
                if not capture.exists() or capture.stat().st_size < 32 * 1024**2:
                    with capture.open("a") as output:
                        output.write(json.dumps(sample) + "\n")
                if args.once:
                    print(json.dumps(sample))
                    return
                if (not args.keep_running and sample["soak"]["state"] != "RUNNING"
                        and (op / "mechanism-result.json").exists()):
                    return
            except Exception as exc:
                print(json.dumps({"at": time.time(), "observer_error": type(exc).__name__,
                                  "detail": str(exc)[:500], "previous_snapshot_not_retimestamped": True}),
                      flush=True)
                if args.once:
                    raise
            time.sleep(max(1, args.interval - (time.monotonic() - start)))


if __name__ == "__main__":
    main()
