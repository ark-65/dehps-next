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
    for service in ("database", "api", "source", "worker", "planner", "steward", "reporter")
]
NAMES += ["dehps-next-inference"]


class Docker(http.client.HTTPConnection):
    def __init__(self):
        # Image/build-cache accounting can exceed ten seconds during real fits.
        # Keep a bounded request and the application's90s freshness gate; never
        # replace missing physical accounting with an optimistic admission.
        super().__init__("localhost", timeout=30)

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(self.timeout)
        self.sock.connect("/var/run/docker.sock")


def get(path, optional=False):
    # Retry only an infrastructure void, with the identical read-only request.
    # Two bounded failures still invalidate telemetry and close admission.
    for attempt in range(2):
        connection = Docker()
        try:
            connection.request("GET", path)
            response = connection.getresponse()
            if optional and response.status == 404:
                return None
            if response.status != 200:
                raise RuntimeError(f"Docker telemetry returned {response.status}")
            return json.loads(response.read())
        except (TimeoutError, ConnectionResetError, ConnectionAbortedError):
            if attempt:
                raise
            logging.getLogger("dehps_next_host").warning("Retrying bounded Docker read: %s", path)
        finally:
            connection.close()


def container_image_size(info):
    image = get(f"/images/{info['Image']}/json", optional=True)
    if image is not None:
        return image["Size"]
    # Docker's containerd store can stop resolving an old config ID after tag replacement.
    # The container's full rootfs size is a conservative bound including shared base layers.
    size = info.get("SizeRootFs", 0)
    if size <= 0:
        raise RuntimeError("No conservative size for the still-referenced Next container image")
    return size


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
    observed_at = datetime.now(UTC)
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
        if info["Image"] not in images:
            images[info["Image"]] = container_image_size(info)
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
        if development["Image"] not in images:
            images[development["Image"]] = container_image_size(development)
    base = get("/images/dehps-next-dependencies:p0p1/json")
    images[base["Id"]] = base["Size"]
    # Docker's global disk-usage scan can stall for minutes while a model generates.
    # Bound shared cache by its entire backing device instead of treating a slow
    # optional accounting scan as missing physical memory/disk telemetry. This is
    # deliberately an upper bound, never reported as attributed Next consumption.
    docker_root = Path("/var/lib/docker")
    if docker_root.stat().st_dev != ROOT.stat().st_dev:
        raise RuntimeError("Verify Docker storage accounting on the separately mounted device")
    shared_cache = disk.total
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
        "at": observed_at.isoformat(),
        "sample_completed_at": datetime.now(UTC).isoformat(),
        "complete": True,
        "disk_total": disk.total,
        "disk_free": disk.free,
        "memory_total": memory["MemTotal"],
        "memory_available": memory["MemAvailable"],
        "logical_cpus": os.cpu_count(),
        "categories": categories,
        "containers": containers,
        "shared_build_cache_upper_bytes": shared_cache,
        "shared_build_cache_accounting": "WHOLE_BACKING_DEVICE_UPPER_BOUND;NOT_OBSERVED_CACHE_USAGE",
        "owned_upper_bytes": sum(categories.values())
        + shared_cache
        + repo
        + other
        + sum(c["writable_bytes"] for c in containers.values()),
        "accounting": "conservative logical images/log maxima plus whole-device shared-cache bound; physical admission uses fresh free disk and memory",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--output", type=Path, help="Isolated acceptance receipt inside this repository's runtime")
    args = parser.parse_args()
    target = args.output.resolve() if args.output else ROOT / "runtime/host/telemetry.json"
    if not target.is_relative_to(ROOT / "runtime"):
        raise SystemExit("Telemetry output must remain inside the named Next runtime")
    target.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            value = sample()
        except Exception as exc:
            logging.getLogger("dehps_next_host").exception("Next telemetry failed")
            value = {
                "owner": "dehps-next",
                "at": datetime.now(UTC).isoformat(),
                "complete": False,
                "error": type(exc).__name__,
            }
        else:
            try:
                value["image_gc"] = retire_images()
            except Exception as exc:
                # Fresh, complete physical/accounting observations remain valid.
                # Failed retirement performs no optimistic admission or deletion.
                logging.getLogger("dehps_next_host").exception("Next image retirement held")
                value["image_gc"] = {"state": "HOLD", "error": type(exc).__name__}
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
