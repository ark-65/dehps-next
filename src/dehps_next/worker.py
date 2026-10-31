import json
import logging
import resource
import signal
import socket
import threading
import time

import torch
from psycopg.errors import DeadlockDetected, LockNotAvailable, SerializationFailure
from psycopg.errors import Error as DatabaseError

from .calendar import ZONE
from .domain import now
from .errors import DomainError, LeaseLost
from .pipeline import Pipeline
from .research import Research
from .research_compute import close_origin_pool
from .resources import Resources
from .scheduler import Scheduler
from .training_window import TRAINING_KINDS
from .training_window import status as training_window

log = logging.getLogger("dehps_next")


def event(name, **values):
    log.info(json.dumps({"at": now().isoformat(), "event": name, **values}, sort_keys=True))


class Worker:
    def __init__(self, db, artifacts, worker_id=None, role="all", clock=None):
        self.db, self.artifacts = db, artifacts
        self.id = worker_id or socket.gethostname()
        self.stop = threading.Event()
        self.scheduler = Scheduler(db, artifacts)
        self.pipeline = Pipeline(db, artifacts)
        self.research = Research(db, artifacts)
        self.role = role
        # CLI always uses wall time; explicit clock is for isolated calendar acceptance only.
        self.clock = clock or now
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
        job = self.db.claim(self.id, self.role, at=self.clock())
        if job is None:
            with self.db.pool.connection() as c:
                paused = training_window(c, self.clock())["paused"]
            if paused:
                close_origin_pool()
            self.status("PAUSED_DRAW_WINDOW" if paused else "IDLE")
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
        window_checked = [0.0, None]

        def pulse():
            if lost.is_set():
                raise LeaseLost()
            if self.stop.is_set():
                raise DomainError("INTERRUPTED", "Worker was asked to stop; task is recoverable")
            if job["kind"] in TRAINING_KINDS:
                clock = self.clock()
                # At17:00 always invalidate even a recent before-boundary observation.
                phase = (
                    clock.astimezone(ZONE).date(),
                    clock.astimezone(ZONE).hour >= 17,
                )
                if time.monotonic() - window_checked[0] >= 0.5 or phase != window_checked[1]:
                    with self.db.pool.connection() as c:
                        window = training_window(c, clock)
                    window_checked[:] = [time.monotonic(), phase]
                    if window["paused"]:
                        raise DomainError(
                            "YIELD_DRAW_PAUSE",
                            "Pause parameter updates until the official result is verified",
                        )
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

        def cgroup_cpu():
            try:
                from pathlib import Path

                value = dict(
                    line.split() for line in Path("/sys/fs/cgroup/cpu.stat").read_text().splitlines()
                )
                return int(value["usage_usec"]) / 1e6
            except (OSError, KeyError, ValueError):
                return None

        cgroup_started = cgroup_cpu()
        cpu_started = time.process_time()
        children = resource.getrusage(resource.RUSAGE_CHILDREN)
        child_cpu_started = children.ru_utime + children.ru_stime
        try:
            if job["kind"] == "RESEARCH_EVALUATE":
                torch.set_num_threads(self.db.settings.training_threads)
            if (
                job["kind"] == "RESEARCH_EVALUATE"
                and self.research.context(job)["config"].get("numeric_threads", 2) != torch.get_num_threads()
            ):
                raise DomainError(
                    "NUMERIC_THREADS_CHANGED", "Frozen campaign threads differ from the compute worker"
                )
            if (
                job["kind"] == "RESEARCH_EVALUATE"
                and self.research.context(job)["config"].get("origin_processes", 1)
                != self.db.settings.origin_processes
            ):
                raise DomainError(
                    "ORIGIN_PROCESSES_CHANGED",
                    "Finish the frozen campaign before changing origin concurrency",
                )
            pulse()
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
            if isinstance(exc, (LockNotAvailable, DeadlockDetected, SerializationFailure)):
                code = "YIELD_DATABASE_CONTENTION"
            try:
                if code.startswith("YIELD_") or code in (
                    "LOCAL_INFERENCE_UNAVAILABLE",
                    "LOCAL_MODEL_MISSING",
                    "INTERRUPTED",
                ):
                    self.db.defer(
                        job,
                        code,
                        300
                        if code in ("LOCAL_INFERENCE_UNAVAILABLE", "LOCAL_MODEL_MISSING")
                        and job["kind"] != "RESEARCH_PLAN"
                        else 15,
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
            children = resource.getrusage(resource.RUSAGE_CHILDREN)
            cpu_seconds = (
                time.process_time() - cpu_started + children.ru_utime + children.ru_stime - child_cpu_started
            )
            cgroup_ended = cgroup_cpu()
            if cgroup_started is not None and cgroup_ended is not None:
                cpu_seconds = max(0, cgroup_ended - cgroup_started)
            self.resources.finish(job["token"], time.monotonic() - started, cpu_seconds)
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
        close_origin_pool()
        self.status("STOPPED")
        return done
