import fcntl
import hashlib
import os
import shutil
import tempfile
from contextlib import contextmanager

from .errors import DomainError


class Artifacts:
    def __init__(self, settings):
        self.settings = settings
        self.root = settings.runtime
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, relative):
        p = self.root / relative
        if p.is_symlink() or not p.resolve().is_relative_to(self.root.resolve()):
            raise DomainError("INVALID_ARTIFACT_PATH", "Artifact escapes owned runtime")
        return p

    @contextmanager
    def locked(self):
        with self.path(".quota.lock").open("a") as h:
            fcntl.flock(h, fcntl.LOCK_EX)
            yield

    def usage(self):
        total = 0
        for p in self.root.rglob("*"):
            if p.is_symlink():
                raise DomainError("RUNTIME_SYMLINK", "Symlink in owned runtime is not allowed")
            try:
                if p.is_file():
                    total += p.stat().st_size
            except FileNotFoundError:
                continue  # A completed task may concurrently retire its owned checkpoints.
        return total

    def ensure_capacity(self, reserve=8 * 1024 * 1024):
        if (
            self.usage() + reserve > self.settings.quota_bytes
            or shutil.disk_usage(self.root).free < reserve + 64 * 1024 * 1024
        ):
            raise DomainError("STORAGE_QUOTA", "Insufficient owned-runtime or filesystem space")

    def write(self, data, *, category="objects", key=None):
        if len(data) > self.settings.artifact_bytes:
            raise DomainError("ARTIFACT_TOO_LARGE", "Per-artifact limit exceeded")
        sha = hashlib.sha256(data).hexdigest()
        relative = f"{category}/{key or sha}"
        p = self.path(relative)
        with self.locked():
            # Reserve the whole temporary write as well as the existing file.
            self.ensure_capacity(len(data))
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, temporary = tempfile.mkstemp(prefix=".pending-", dir=p.parent)
            try:
                with os.fdopen(fd, "wb") as h:
                    h.write(data)
                    h.flush()
                    os.fsync(h.fileno())
                os.replace(temporary, p)
                d = os.open(p.parent, os.O_DIRECTORY)
                try:
                    os.fsync(d)
                finally:
                    os.close(d)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return {"path": relative, "sha256": sha, "bytes": len(data)}

    def read(self, ref):
        if ref["bytes"] > self.settings.artifact_bytes:
            raise DomainError("ARTIFACT_TOO_LARGE", "Read limit exceeded")
        p = self.path(ref["path"])
        with p.open("rb") as h:
            data = h.read(self.settings.artifact_bytes + 1)
        if len(data) != ref["bytes"] or hashlib.sha256(data).hexdigest() != ref["sha256"]:
            raise DomainError("ARTIFACT_CORRUPT", "Artifact size or digest differs")
        return data

    def cleanup_checkpoints(self, job_id):
        # Only called after the task completion transaction committed.
        with self.locked():
            directory = self.path("checkpoints")
            if directory.exists():
                for p in directory.glob(f"{job_id}-*.pt"):
                    self.path(str(p.relative_to(self.root))).unlink()
