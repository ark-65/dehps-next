"""Host-side read-only observations; write only the named Next operation snapshot."""

import argparse
import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRIMARY = ("dehps-next-p0p1-worker-1", "dehps-next-p0p1-planner-1", "dehps-next-p0p1-steward-1")


def run(args):
    return subprocess.check_output(args, text=True, timeout=8, stderr=subprocess.DEVNULL).strip()


def observe():
    sample = {"observed_at": time.time()}
    memory = Path("/proc/meminfo").read_text()
    sample["memory_available_bytes"] = int(re.search(r"MemAvailable:\s+(\d+)", memory)[1]) * 1024
    pressure = Path("/proc/pressure/memory").read_text()
    sample["memory_full_avg10"] = float(re.search(r"full avg10=([\d.]+)", pressure)[1])
    try:
        value = run(["gdbus", "call", "--session", "--dest", "org.gnome.Mutter.IdleMonitor",
                     "--object-path", "/org/gnome/Mutter/IdleMonitor/Core",
                     "--method", "org.gnome.Mutter.IdleMonitor.GetIdletime"])
        sample["desktop_idle_seconds"] = int(re.fullmatch(r"\(uint64 (\d+),\)", value)[1]) / 1000
    except (subprocess.SubprocessError, TypeError, ValueError):
        sample["desktop_idle_seconds"] = None
    sample["primary_running"] = run(["docker", "inspect", "--format", "{{.State.Running}}", *PRIMARY]).splitlines() == ["true"] * 3
    query = """SELECT json_build_object(
      'training_progress_age_seconds',extract(epoch FROM now()-max(completed_at)),
      'latest_completed_at',max(completed_at),
      'fresh_training_workers',(SELECT count(*) FROM worker_status
        WHERE heartbeat_at>now()-interval '45 seconds' AND state IN ('RUNNING','IDLE')))
      FROM research_nodes WHERE completed_at IS NOT NULL"""
    sample.update(json.loads(run(["docker", "exec", "dehps-next-p0p1-database-1", "psql", "-U", "dehps_next",
                                  "-d", "dehps_next", "-X", "-At", "-v", "ON_ERROR_STOP=1", "-c", query])))
    return sample


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--operation", type=Path, required=True)
    parser.add_argument("--repository-root", type=Path, default=ROOT)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    operation = args.operation.resolve()
    if operation.parent != args.repository_root.resolve() / "runtime/operations":
        raise SystemExit("Use a direct Next runtime/operations child")
    while True:
        try:
            sample = observe()
            temporary = operation / "admission.pending"
            temporary.write_text(json.dumps(sample) + "\n")
            temporary.replace(operation / "admission.json")
            if args.once:
                print(json.dumps(sample))
        except (OSError, subprocess.SubprocessError, ValueError, TypeError) as exc:
            print(json.dumps({"monitor_error": type(exc).__name__, "at": time.time()}), flush=True)
            if args.once:
                raise
        if args.once:
            return
        time.sleep(10)


if __name__ == "__main__":
    main()
