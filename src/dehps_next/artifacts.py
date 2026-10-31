import fcntl
import hashlib
import os
import shutil
import tempfile
from contextlib import contextmanager

from .errors import DomainError


class Artifacts:
    def __init__(self, settings, db=None):
        self.settings = settings
        self.db = db
        self.reservation_token = None
        if db is not None:
            db.artifacts = self
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
        if shutil.disk_usage(self.root).free < reserve + max(
            20 * 1024**3, shutil.disk_usage(self.root).total * 0.05
        ):
            raise DomainError("STORAGE_QUOTA", "Insufficient owned-runtime or filesystem space")

    def write(self, data, *, category="objects", key=None):
        if len(data) > self.settings.artifact_bytes:
            raise DomainError("ARTIFACT_TOO_LARGE", "Per-artifact limit exceeded")
        sha = hashlib.sha256(data).hexdigest()
        relative = f"{category}/{key or sha}"
        p = self.path(relative)
        with self.locked():
            if self.db and self.reservation_token:
                with self.db.pool.connection() as c:
                    if not c.execute(
                        """UPDATE resource_reservations SET written=written+%s
                        WHERE token=%s AND state='ACTIVE' AND written+%s<=write_reserved RETURNING token""",
                        (len(data), self.reservation_token, len(data)),
                    ).fetchone():
                        raise DomainError("YIELD_WRITE_BUDGET", "Task exhausted its reserved write allowance")
            # Reserve the whole temporary write as well as the existing file.
            pending = int(
                self.db.rows(
                    "SELECT coalesce(sum(greatest(0,write_reserved-written)),0) AS n FROM resource_reservations WHERE state='ACTIVE'"
                )[0]["n"]
                if self.db
                else 0
            )
            self.ensure_capacity(len(data) + pending)
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
                if self.db:
                    from psycopg.types.json import Jsonb

                    with self.db.pool.connection() as c:
                        c.execute(
                            """INSERT INTO artifact_catalog(path,ref,category) VALUES(%s,%s,%s)
                            ON CONFLICT(path) DO UPDATE SET ref=excluded.ref,state='LIVE',candidate_at=NULL,
                            writer_until=now()+interval '5 minutes',deleted_at=NULL""",
                            (
                                relative,
                                Jsonb({"path": relative, "sha256": sha, "bytes": len(data)}),
                                category,
                            ),
                        )
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        return {"path": relative, "sha256": sha, "bytes": len(data)}

    def read(self, ref):
        if self.db:
            row = self.db.rows("SELECT state FROM artifact_catalog WHERE path=%s", (ref["path"],))
            if row and row[0]["state"] == "DELETED":
                raise DomainError(
                    "ARTIFACT_RETIRED", "Optional research detail retired; summary and digest retained"
                )
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
