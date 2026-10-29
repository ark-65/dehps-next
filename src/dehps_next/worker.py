import json
import logging
import signal
import socket
import threading
import time

import torch
from psycopg.errors import Error as DatabaseError

from .domain import now
from .errors import DomainError, LeaseLost
from .pipeline import Pipeline
from .research import Research
from .resources import Resources
from .scheduler import Scheduler

log = logging.getLogger("dehps_next")


def event(name, **values):
    log.info(json.dumps({"at": now().isoformat(), "event": name, **values}, sort_keys=True))


class Worker:
    def __init__(self, db, artifacts, worker_id=None, role="all"):
        self.db, self.artifacts = db, artifacts
        self.id = worker_id or socket.gethostname()
        self.stop = threading.Event()
        self.scheduler = Scheduler(db, artifacts)
        self.pipeline = Pipeline(db, artifacts)
        self.research = Research(db, artifacts)
        self.role = role
        self.resources = Resources(db)
        self.artifacts.db = db
        db.artifacts = artifacts
        torch.set_num_threads(db.settings.threads)

    def status(self, state, job=None, error=None):
        with self.db.pool.connection() as c:
            c.execute(
                """INSERT INTO worker_status(id,state,current_job,error_code) VALUES(%s,%s,%s,%s)
                ON CONFLICT(id) DO UPDATE SET state=excluded.state,current_job=excluded.current_job,
                error_code=excluded.error_code,heartbeat_at=now()""",
                (self.id, state, job, error),
            )

    def once(self):
        try:
            self.scheduler.reconcile()
            self.research.reconcile()
        except DomainError as exc:
            self.status("BLOCKED", error=exc.code)
            raise
        job = self.db.claim(self.id, self.role)
        if job is None:
            self.status("IDLE")
            return False
        self.status("RUNNING", job["id"])
        self.artifacts.reservation_token = job["token"]
        finished, lost = threading.Event(), threading.Event()

        def heartbeat():
            while not finished.wait(max(1, self.db.settings.lease_seconds / 4)):
                try:
                    self.db.heartbeat(job)
                    self.status("RUNNING", job["id"])
                except Exception:
                    log.exception("Heartbeat failed; stopping this execution before result submission")
                    lost.set()
                    return

        checked = [0.0]

        def pulse():
            if lost.is_set():
                raise LeaseLost()
            if self.stop.is_set():
                raise DomainError("INTERRUPTED", "Worker was asked to stop; task is recoverable")
            if job["research_node_id"] and time.monotonic() - checked[0] > 1:
                checked[0] = time.monotonic()
                if time.monotonic() - started > job["admission"]["wall_cap"]:
                    raise DomainError("YIELD_WALL_BUDGET", "Resume from the last saved block")
                if job["kind"] == "RESEARCH_EVALUATE" and self.db.rows(
                    "SELECT 1 FROM jobs WHERE cycle_id IS NOT NULL AND state IN ('READY','RUNNING') LIMIT 1"
                ):
                    raise DomainError(
                        "YIELD_CORE_PRIORITY", "Yield compute lane to formal learning/prediction"
                    )

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        started = time.monotonic()
        cpu_started = time.process_time()
        try:
            if job["kind"].startswith("RESEARCH_"):
                self.research.execute(job, pulse)
            else:
                self.pipeline.execute(job, pulse)
            event(
                "job_succeeded",
                kind=job["kind"],
                job=job["id"],
                attempt=job["token"],
                elapsed_seconds=round(time.monotonic() - started, 4),
            )
        except Exception as exc:
            code = exc.code if isinstance(exc, DomainError) else type(exc).__name__
            try:
                if code.startswith("YIELD_") or code in (
                    "LOCAL_INFERENCE_UNAVAILABLE",
                    "LOCAL_MODEL_MISSING",
                    "INTERRUPTED",
                ):
                    self.db.defer(
                        job,
                        code,
                        300 if code in ("LOCAL_INFERENCE_UNAVAILABLE", "LOCAL_MODEL_MISSING") else 15,
                    )
                else:
                    self.db.fail(job, code)
            except LeaseLost:
                pass
            event("job_failed", kind=job["kind"], job=job["id"], code=code)
            if not isinstance(exc, DomainError):
                log.exception("Unexpected task error")
        finally:
            finished.set()
            thread.join(timeout=3)
            self.resources.finish(job["token"], time.monotonic() - started, time.process_time() - cpu_started)
            self.artifacts.reservation_token = None
        return True

    def run(self, max_jobs=None):
        signal.signal(signal.SIGTERM, lambda *_: self.stop.set())
        signal.signal(signal.SIGINT, lambda *_: self.stop.set())
        done = 0
        while not self.stop.is_set() and (max_jobs is None or done < max_jobs):
            try:
                if self.once():
                    done += 1
                    continue
            except (DomainError, DatabaseError) as exc:
                event("worker_blocked", code=getattr(exc, "code", type(exc).__name__))
            self.stop.wait(self.db.settings.poll_seconds)
        self.status("STOPPED")
        return done
