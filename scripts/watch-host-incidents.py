"""Bounded host evidence and fail-closed admission holds for owned Next experiments."""

import argparse
import json
import os
import re
import subprocess
import time
from pathlib import Path

FAULT = re.compile(r"Fence expiration time out|GPU HANG|GPU.*wedged|Out of memory|oom-kill|Kernel panic|hard LOCKUP", re.I)
OWNER = "next-host-incident-watch-v1"


def publish(path, value):
    temporary = path.with_suffix(".pending")
    with temporary.open("w") as stream:
        json.dump(value, stream)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def sample(root):
    output = root / "runtime/host/incidents"
    output.mkdir(parents=True, exist_ok=True)
    path = output / "state.json"
    previous = json.loads(path.read_text()) if path.exists() else {}
    boot = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    at = time.time()
    events = []
    if previous and previous["boot_id"] != boot:
        events.append({"kind": "BOOT_CHANGED", "previous_boot": previous["boot_id"],
                       "last_sample": previous["at"], "at": at,
                       "meaning": "coverage gap; does not distinguish orderly shutdown from crash"})
    command = ["journalctl", "-k", "-b", "0", "-o", "json", "--no-pager", "-n", "100"]
    if previous.get("boot_id") == boot and previous.get("cursor"):
        command += ["--after-cursor", previous["cursor"]]
    result = subprocess.run(command, capture_output=True, text=True, timeout=5)
    cursor = previous.get("cursor") if previous.get("boot_id") == boot else None
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            row = json.loads(line)
            cursor = row.get("__CURSOR", cursor)
            message = row.get("MESSAGE", "")
            if FAULT.search(message):
                events.append({"kind": "KERNEL_FAULT", "message": message[:1000],
                               "at": at, "kernel_at_us": row.get("__REALTIME_TIMESTAMP")})
    incident = output / "admission-hold.json"
    if events and not incident.exists():
        publish(incident, {"owner": OWNER, "boot_id": boot, "at": at,
                           "events": events[-20:], "automatic_release": False})
    held = 0
    # Frozen operation drivers remain unchanged. Their existing controller checks
    # this marker before starting a slot. Never replace another owner's hold.
    if incident.exists():
        for driver in (root / "runtime/operations").glob("qwen-*/drivers/qwen-acceptance-admission.py"):
            hold = driver.parents[1] / "operator-boundary-hold.json"
            try:
                with hold.open("x") as stream:
                    json.dump({"owner": OWNER, "at": at, "kind": "HOST_INCIDENT_HOLD",
                               "reason": "Review runtime/host/incidents/admission-hold.json before new GPU experiments"}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
            except FileExistsError:
                pass
            held += 1
    memory = {k: int(v.split()[0]) * 1024 for k, v in
              (line.split(":", 1) for line in Path("/proc/meminfo").read_text().splitlines())
              if k in ("MemAvailable", "MemTotal", "SwapFree", "SwapTotal")}
    state = {"at": at, "boot_id": boot, "cursor": cursor, "memory": memory,
             "memory_pressure": Path("/proc/pressure/memory").read_text(),
             "journal_read_ok": result.returncode == 0,
             "admission_hold": incident.exists(), "owned_operation_holds": held}
    history = output / "samples.jsonl"
    if history.exists() and history.stat().st_size >= 2 * 1024**2:
        history.replace(output / "samples.previous.jsonl")
    with history.open("a") as stream:
        stream.write(json.dumps({**state, "events": events}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    publish(path, state)
    return state


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    while True:
        try:
            print(json.dumps(sample(args.root)), flush=True)
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            print(json.dumps({"at": time.time(), "error": type(exc).__name__}), flush=True)
        if args.once:
            break
        time.sleep(15)


if __name__ == "__main__":
    main()
