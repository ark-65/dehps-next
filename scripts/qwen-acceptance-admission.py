"""Scheduling only: serialized acceptance can accelerate while the desktop is idle."""

import json
import time
from pathlib import Path

POLICY = {
    "kind": "QWEN_ACCEPTANCE_IDLE_ADMISSION_V1",
    "default_start_interval_seconds": 300,
    "idle_cooldown_seconds": 30,
    "desktop_idle_min_seconds": 120,
    "snapshot_max_age_seconds": 30,
    "minimum_memory_available_bytes": 6 * 1024**3,
    "maximum_memory_full_avg10": 0.5,
    "maximum_training_progress_age_seconds": 300,
    "parallel_requests": 1,
    "production_cadence_changed": False,
}


def decision(snapshot, current, last_start, last_wall):
    """Unknown observations retain the old cadence; known resource faults hold admission."""
    default = max(0, last_start + POLICY["default_start_interval_seconds"] - current)
    age = current - snapshot.get("observed_at", 0)
    if not 0 <= age <= POLICY["snapshot_max_age_seconds"]:
        return default, "MONITOR_UNAVAILABLE_OR_STALE;ORIGINAL_INTERVAL"
    if (
        snapshot.get("memory_available_bytes", 0) < POLICY["minimum_memory_available_bytes"]
        or snapshot.get("memory_full_avg10", 100) > POLICY["maximum_memory_full_avg10"]
        or not snapshot.get("primary_running")
        or snapshot.get("training_progress_age_seconds", 1e9)
        > POLICY["maximum_training_progress_age_seconds"]
        or snapshot.get("fresh_training_workers", 0) < 2
    ):
        return 10, "RESOURCE_OR_TRAINING_GUARD"
    idle = snapshot.get("desktop_idle_seconds")
    if type(idle) not in (int, float) or idle < POLICY["desktop_idle_min_seconds"]:
        return default, "DESKTOP_ACTIVE_OR_UNKNOWN;ORIGINAL_INTERVAL"
    return max(0, last_start + last_wall + POLICY["idle_cooldown_seconds"] - current), "IDLE_SERIAL_COOLDOWN"


def wait(db, snapshot_path, event_path):
    rows = db.rows("""SELECT created_at,metrics,state FROM research_model_calls
        WHERE stage LIKE 'CANDIDATE_SELECTION_V4_%%' ORDER BY id DESC LIMIT 1""")
    last = rows[0] if rows else None
    if last and last["state"] == "RESERVED":
        raise RuntimeError("Another logical request is active; never overlap acceptance calls")
    while True:
        try:
            snapshot = json.loads(Path(snapshot_path).read_text())
        except (OSError, ValueError):
            snapshot = {}
        current = time.time()
        start = last["created_at"].timestamp() if last else 0
        wall = (last["metrics"] or {}).get("wall_seconds", 300) if last else 0
        if type(wall) not in (int, float) or wall < 0:
            wall = 300
        delay, reason = decision(snapshot, current, start, wall)
        event = {"observed_at": current, "reason": reason, "wait_seconds": round(delay, 3),
                 "snapshot_observed_at": snapshot.get("observed_at"), "last_call_start": start,
                 "last_call_wall_seconds": wall, "policy": POLICY["kind"]}
        with Path(event_path).open("a") as stream:
            stream.write(json.dumps(event) + "\n")
        if delay <= 0:
            return event
        time.sleep(min(10, delay))
