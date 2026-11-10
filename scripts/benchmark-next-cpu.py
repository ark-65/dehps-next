"""Temporarily benchmark only the Next training slice; always restore its quota."""
import os
import sys
import signal
import pwd
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT = "dehpsnext-training.slice"

def read_property(name):
    return subprocess.check_output(["systemctl", "show", UNIT, "-p", name, "--value"], text=True).strip()

def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with administrator authentication in the host terminal.")
    if read_property("EffectiveCPUs") != "0-19" or read_property("CPUQuotaPerSecUSec") != "8s":
        raise SystemExit("Unexpected current Next allocation; no changes made.")
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
    driver = "whole-worker-benchmark.py" if sys.argv[1:] == ["--whole-worker"] else "benchmark-cpu.py"
    if sys.argv[1:] not in ([], ["--whole-worker"]):
        raise SystemExit("Only the frozen fitter or whole-worker benchmark is supported.")
    owner = pwd.getpwuid(ROOT.stat().st_uid).pw_name
    command = ["runuser", "-u", owner, "--", "docker", "compose", "--ansi", "never", "-f", "compose.yaml",
               "-f", "runtime/lock-repair-acceptance/rollout.yaml", "-f",
               "runtime/red-calibration-20261110/benchmark.yaml", "run", "--rm", "--no-deps", "-T",
               "--entrypoint", "python", "api", "/app/runtime/calibration/" + driver]
    try:
        subprocess.run(["systemctl", "set-property", "--runtime", UNIT, "CPUQuota=2000%"], check=True)
        subprocess.run(command, cwd=ROOT, check=True, timeout=1200)
    finally:
        subprocess.run(["systemctl", "set-property", "--runtime", UNIT, "CPUQuota=800%"], check=True)
        print("Next training quota restored to8 CPU; host allocation and legacy services untouched.")

if __name__ == "__main__":
    main()
