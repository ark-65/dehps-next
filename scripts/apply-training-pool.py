"""Apply the measured Next-only12-CPU profile after reviewed frozen acceptance."""

import json
import os
import subprocess
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[1]
UNIT = "dehpsnext-training.slice"


def prop(name):
    return subprocess.check_output(["systemctl", "show", UNIT, "-p", name, "--value"], text=True).strip()


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run using administrator authentication; no credentials are stored.")
    evidence = json.loads((ROOT / "runtime/red-calibration-20261110/whole-worker-benchmark.json").read_text())
    cases = evidence["cases"]
    if len(cases) != 8 or {r["processes"] for r in cases} != {8, 12}:
        raise SystemExit("Require the complete paired actual Worker benchmark.")
    for variant in ("A", "B"):
        if len({r["result_digest"] for r in cases if r["variant"] == variant}) != 1:
            raise SystemExit("Probability/parameter evidence differs across pool sizes.")
    full = {n: mean(r["whole_worker_seconds"] for r in cases if r["processes"] == n) for n in (8, 12)}
    if full[12] >= full[8] * .9:
        raise SystemExit("No measured whole-Worker improvement large enough to promote the pool.")
    source = ROOT / "deploy/systemd" / UNIT
    target = Path("/etc/systemd/system") / UNIT
    new = source.read_bytes()
    before = target.read_bytes()
    expected_old = new.replace(b"twelve-CPU", b"eight-CPU").replace(b"CPUQuota=1200%", b"CPUQuota=800%")
    if before != expected_old or prop("EffectiveCPUs") != "0-19" or prop("CPUQuotaPerSecUSec") != "8s":
        raise SystemExit("Unexpected existing allocation or unit source; no changes made.")
    try:
        target.write_bytes(new)
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "set-property", "--runtime", UNIT, "CPUQuota=1200%"], check=True)
        if prop("CPUQuotaPerSecUSec") != "12s" or prop("EffectiveCPUs") != "0-19":
            raise RuntimeError("The measured Next-only profile was not applied.")
    except Exception:
        target.write_bytes(before)
        subprocess.run(["systemctl", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "set-property", "--runtime", UNIT, "CPUQuota=800%"], check=True)
        raise
    print(json.dumps({"unit": UNIT, "cpu_quota": 12, "allowed_cpus": "0-19",
                      "measured_mean_whole_worker_seconds": full, "host_units_unchanged": True}))


if __name__ == "__main__":
    main()
