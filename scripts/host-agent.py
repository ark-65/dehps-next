"""Next host accounting and label-scoped image retirement; applications get no Docker socket."""

import argparse
import http.client
import json
import logging
import os
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from shutil import disk_usage

ROOT = Path(__file__).resolve().parents[1]
NAMES = [
    f"dehps-next-p0p1-{service}-1"
    for service in ("database", "api", "source", "worker", "planner", "steward")
]
NAMES += ["dehps-next-inference"]


class Docker(http.client.HTTPConnection):
    def __init__(self):
        super().__init__("localhost", timeout=10)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/var/run/docker.sock")


def get(path, optional=False):
    connection = Docker()
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        if optional and response.status == 404:
            return None
        if response.status != 200:
            raise RuntimeError(f"Docker telemetry returned {response.status}")
        return json.loads(response.read())
    finally:
        connection.close()


def retire_images():
    ledger_path = ROOT / "runtime/host/image-gc.json"
    ledger = (
        json.loads(ledger_path.read_text())
        if ledger_path.exists()
        else {"candidates": {}, "deleted": 0, "recent": []}
    )
    images = get("/images/json?filters=%7B%22label%22%3A%5B%22io.dehps-next.owner%3Ddehps-next%22%5D%7D")
    images.sort(key=lambda image: image["Created"], reverse=True)
    used = {container["ImageID"] for container in get("/containers/json?all=true")}
    for image in images:
        identity = image["Id"]
        if identity in used or image.get("RepoTags") or time.time() - image["Created"] < 7 * 86400:
            ledger["candidates"].pop(identity, None)
            continue
        marked = ledger["candidates"].setdefault(identity, time.time())
        if time.time() - marked < 60:
            continue
        current = get(f"/images/{identity}/json")
        used_now = {container["ImageID"] for container in get("/containers/json?all=true")}
        if (
            current["Config"].get("Labels", {}).get("io.dehps-next.owner") != "dehps-next"
            or identity in used_now
            or current.get("RepoTags")
        ):
            continue
        connection = Docker()
        try:
            connection.request("DELETE", f"/images/{identity}?force=false")
            response = connection.getresponse()
            response.read()
            if response.status == 200:
                ledger["deleted"] += 1
                ledger["recent"].append(
                    {
                        "image": identity,
                        "at": datetime.now(UTC).isoformat(),
                        "reason": "OWNED_UNREFERENCED_7D_RECHECKED",
                    }
                )
                ledger["candidates"].pop(identity, None)
        finally:
            connection.close()
    ledger["recent"] = ledger["recent"][-128:]
    ledger["candidates"] = dict(list(ledger["candidates"].items())[-128:])
    temporary = ledger_path.with_suffix(".pending")
    temporary.write_text(json.dumps(ledger, sort_keys=True) + "\n")
    temporary.replace(ledger_path)
    return {"deleted_lifetime": ledger["deleted"], "candidates": len(ledger["candidates"])}


def size(path, allow_links=False):
    if path.is_symlink():
        if allow_links:
            return path.lstat().st_size
        raise RuntimeError("Symlink in owned telemetry scope")
    if not path.exists():
        return 0
    total = 0
    for parent, dirs, files in os.walk(path, followlinks=False):
        for name in dirs + files:
            item = Path(parent) / name
            if item.is_symlink() and not allow_links:
                raise RuntimeError("Symlink in owned telemetry scope")
        for name in files:
            try:
                total += (Path(parent) / name).lstat().st_size
            except FileNotFoundError:
                continue  # Atomic writers and GC can retire a listed temporary file.
        total += sum(
            (Path(parent) / name).lstat().st_size for name in dirs if (Path(parent) / name).is_symlink()
        )
    return total


def sample():
    if ROOT.name != "dehps-next" or not (ROOT / "AGENT.md").is_file():
        raise RuntimeError("Refusing telemetry outside the named Next repository")
    memory = {
        line.split(":")[0]: int(line.split()[1]) * 1024
        for line in Path("/proc/meminfo").read_text().splitlines()
    }
    disk = disk_usage(ROOT)
    containers, images = {}, {}
    for name in NAMES:
        info = get(f"/containers/{name}/json?size=true")
        if (
            info["Name"] != "/" + name
            or info["Config"].get("Labels", {}).get("com.docker.compose.project") != "dehps-next-p0p1"
        ):
            raise RuntimeError("Container ownership mismatch")
        stats = get(f"/containers/{name}/stats?stream=false&one-shot=true")
        containers[name] = {
            "cpu_ns": stats.get("cpu_stats", {}).get("cpu_usage", {}).get("total_usage", 0),
            "memory": stats.get("memory_stats", {}).get("usage", 0),
            "running": info["State"]["Running"],
            "oom_killed": info["State"].get("OOMKilled", False),
            "writable_bytes": info.get("SizeRw", 0),
        }
        images[info["Image"]] = get(f"/images/{info['Image']}/json")["Size"]
    # Include registered build images, and the fixed dependency cache; never prune shared Docker state.
    for image in get("/images/json?filters=%7B%22label%22%3A%5B%22io.dehps-next.owner%3Ddehps-next%22%5D%7D"):
        images[image["Id"]] = image["Size"]
    development = get("/containers/dehps-next-dev/json?size=true", optional=True)
    if development:
        if not any(
            m.get("Source") == str(ROOT) and m.get("Destination") == "/app" for m in development["Mounts"]
        ):
            raise RuntimeError("Development container ownership mismatch")
        containers["dehps-next-dev"] = {
            "writable_bytes": development.get("SizeRw", 0),
            "running": development["State"]["Running"],
        }
        images[development["Image"]] = get(f"/images/{development['Image']}/json")["Size"]
    base = get("/images/dehps-next-dependencies:p0p1/json")
    images[base["Id"]] = base["Size"]
    df = get("/system/df")
    shared_cache = sum(item.get("Size", 0) for item in df.get("BuildCache", []))
    # Only the Next PostgreSQL volume, measured inside its own named container.
    pg = int(
        subprocess.check_output(
            ["docker", "exec", NAMES[0], "du", "-sb", "/var/lib/postgresql/data"], text=True, timeout=15
        ).split()[0]
    )
    runtime = ROOT / "runtime"
    categories = {
        "application": size(runtime / "application"),
        "inference": size(runtime / "inference"),
        "database": pg,
        "environment": sum(images.values()),
        "backups": size(runtime / "backups"),
        "staging": sum(
            size(p)
            for p in runtime.iterdir()
            if p.is_dir() and p.name not in ("application", "inference", "backups")
        ),
        "logs": len(NAMES) * 15 * 1024**2,
    }
    repo = sum(
        size(p, allow_links=True) if p.is_dir() else p.lstat().st_size
        for p in ROOT.iterdir()
        if p.name != "runtime"
    )
    other = sum(p.stat().st_size for p in runtime.iterdir() if p.is_file() and not p.is_symlink())
    return {
        "owner": "dehps-next",
        "at": datetime.now(UTC).isoformat(),
        "complete": True,
        "disk_total": disk.total,
        "disk_free": disk.free,
        "memory_total": memory["MemTotal"],
        "memory_available": memory["MemAvailable"],
        "logical_cpus": os.cpu_count(),
        "categories": categories,
        "containers": containers,
        "shared_build_cache_upper_bytes": shared_cache,
        "owned_upper_bytes": sum(categories.values())
        + shared_cache
        + repo
        + other
        + sum(c["writable_bytes"] for c in containers.values()),
        "accounting": "logical image sizes and configured log maxima are conservative; all shared build cache charged to total upper bound",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    target = ROOT / "runtime/host/telemetry.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            value = sample()
            value["image_gc"] = retire_images()
        except Exception as exc:
            logging.getLogger("dehps_next_host").exception("Next telemetry failed")
            value = {
                "owner": "dehps-next",
                "at": datetime.now(UTC).isoformat(),
                "complete": False,
                "error": type(exc).__name__,
            }
        temporary = target.with_suffix(".pending")
        temporary.write_text(json.dumps(value, sort_keys=True) + "\n")
        temporary.replace(target)
        history_path = target.with_name("telemetry-history.json")
        history = json.loads(history_path.read_text()) if history_path.exists() else []
        history = (history + [value])[-120:]
        pending = history_path.with_suffix(".pending")
        pending.write_text(json.dumps(history, sort_keys=True) + "\n")
        pending.replace(history_path)
        if args.once:
            print(json.dumps(value))
            return
        time.sleep(15)


if __name__ == "__main__":
    main()
