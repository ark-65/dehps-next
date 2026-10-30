"""Owner-authorized CPU partition. Prepare slice, then move Next containers before applying host limits."""

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNITS = ("system.slice", "user.slice", "init.scope")
NAMES = [
    f"dehps-next-p0p1-{s}-1"
    for s in ("database", "worker", "planner", "steward", "source", "reporter", "api")
]
NAMES.append("dehps-next-inference")
parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=("prepare", "apply", "check", "restore-host"))
args = parser.parse_args()
if os.geteuid() != 0:
    raise SystemExit("Run with administrator authentication; no credentials are stored.")


def call(*argv):
    return subprocess.check_output(argv, text=True).strip()


def properties(unit):
    text = call("systemctl", "show", unit, "-p", "AllowedCPUs", "-p", "EffectiveCPUs")
    return dict(line.split("=", 1) for line in text.splitlines())


receipt = ROOT / "runtime/operations/cpu-pool-20261030"
receipt.mkdir(parents=True, exist_ok=True)
before = receipt / "host-before.json"
if not before.exists():
    before.write_text(json.dumps({u: properties(u) for u in UNITS}, indent=2) + "\n")
    before.chmod(0o644)
if args.mode == "prepare":
    source = ROOT / "deploy/systemd/dehpsnext.slice"
    target = Path("/etc/systemd/system/dehpsnext.slice")
    if target.exists() and target.read_bytes() != source.read_bytes():
        raise SystemExit("Unexpected existing Next slice; review before replacement.")
    target.write_bytes(source.read_bytes())
    target.chmod(0o644)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "--now", "dehpsnext.slice"], check=True)
if args.mode in ("apply", "check"):
    containers = []
    for name in NAMES:
        row = json.loads(call("docker", "inspect", name))[0]
        assert row["State"]["Running"], name
        assert row["HostConfig"]["CgroupParent"] == "dehpsnext.slice", name
        assert row["HostConfig"]["CpusetCpus"] == "0-19", name
        affinity = sorted(os.sched_getaffinity(row["State"]["Pid"]))
        assert affinity and set(affinity) <= set(range(20)), (name, affinity)
        containers.append({"name": name, "affinity": affinity})
    if args.mode == "apply":
        try:
            for unit in UNITS:
                subprocess.run(["systemctl", "set-property", unit, "AllowedCPUs=20-21"], check=True)
        except Exception:
            original = json.loads(before.read_text())
            for unit in UNITS:
                subprocess.run(
                    ["systemctl", "set-property", unit, "AllowedCPUs=" + original[unit]["AllowedCPUs"]],
                    check=True,
                )
            raise
    for unit in UNITS:
        assert properties(unit)["EffectiveCPUs"] == "20-21", (unit, properties(unit))
    assert properties("dehpsnext.slice")["EffectiveCPUs"] == "0-19"
    result = {
        "at": datetime.now().astimezone().isoformat(),
        "host": {u: properties(u) for u in UNITS},
        "next_slice": properties("dehpsnext.slice"),
        "containers": containers,
    }
    p = receipt / "partition-verified.json"
    p.write_text(json.dumps(result, indent=2) + "\n")
    p.chmod(0o644)
    print(json.dumps(result))
if args.mode == "restore-host":
    original = json.loads(before.read_text())
    for unit in UNITS:
        subprocess.run(
            ["systemctl", "set-property", unit, "AllowedCPUs=" + original[unit]["AllowedCPUs"]], check=True
        )
    print(json.dumps({"host_cpu_settings_restored": True, "next_containers_unchanged": True}))
if args.mode == "prepare":
    print(
        json.dumps(
            {
                "next_slice": properties("dehpsnext.slice"),
                "host_limits": "UNCHANGED_UNTIL_ALL_NEXT_CONTAINERS_MOVED",
            }
        )
    )
