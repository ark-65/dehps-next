from dataclasses import asdict
from datetime import timedelta

from psycopg.types.json import Jsonb

from .data import DataService
from .domain import digest, now, timestamp
from .errors import DomainError
from .model import Recipe
from .release import code_identity


class Scheduler:
    def __init__(self, db, artifacts):
        self.db, self.artifacts = db, artifacts
        self.data = DataService(db, artifacts)

    def create_loop(self, name, mode="REPLAY", bootstrap=64, recipe=None, max_cycles=64):
        recipe = recipe or Recipe()
        recipe.validate()
        if not name or len(name) > 80 or mode not in ("REPLAY", "FORWARD"):
            raise DomainError("INVALID_LOOP", "Invalid loop name or evidence mode")
        if not recipe.window + 2 <= bootstrap <= 4999 or not 1 <= max_cycles <= 1000:
            raise DomainError("LOOP_BUDGET", "Invalid bootstrap or cycle budget")
        config = {
            "code_digest": code_identity(),
            "recipe": asdict(recipe),
            "bootstrap": bootstrap,
            "max_cycles": max_cycles,
            "goal": "P1_RED_BLUE_CONTINUOUS_LEARNING",
            "protocol": "prequential-v1",
        }
        with self.db.pool.connection() as c, c.transaction():
            existing = c.execute("SELECT * FROM loops WHERE id=%s FOR UPDATE", (name,)).fetchone()
            if existing:
                if existing["config"] != config or existing["mode"] != mode:
                    raise DomainError("LOOP_CONFLICT", "Existing loop configuration is immutable")
                return existing
            return c.execute(
                "INSERT INTO loops(id,mode,config) VALUES(%s,%s,%s) RETURNING *", (name, mode, Jsonb(config))
            ).fetchone()

    def expect(self, issue, draw_at, deadline):
        draw_at, deadline = timestamp(draw_at), timestamp(deadline)
        if not isinstance(issue, str) or not issue.isdigit() or len(issue) != 7:
            raise DomainError("INVALID_TARGET", "Expected a seven-digit issue")
        if not now() < deadline < draw_at:
            raise DomainError("MISSED_DEADLINE", "Forward target must have a future deadline before draw")
        with self.db.pool.connection() as c, c.transaction():
            old = c.execute("SELECT * FROM targets WHERE issue=%s FOR UPDATE", (issue,)).fetchone()
            if old:
                if old["draw_at"] != draw_at or old["deadline"] != deadline:
                    raise DomainError("TARGET_CONFLICT", "Registered target schedule cannot be rewritten")
                return old
            return c.execute(
                "INSERT INTO targets VALUES(%s,%s,%s,now()) RETURNING *", (issue, draw_at, deadline)
            ).fetchone()

    @staticmethod
    def add_job(c, cycle_id, kind):
        c.execute(
            "INSERT INTO jobs(id,cycle_id,kind) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
            (digest([cycle_id, kind]), cycle_id, kind),
        )

    def reconcile(self):
        self.artifacts.ensure_capacity()
        with self.db.pool.connection() as c, c.transaction():
            if not c.execute("SELECT pg_try_advisory_xact_lock(740133) AS locked").fetchone()["locked"]:
                return
            for loop in c.execute("SELECT * FROM loops ORDER BY created_at").fetchall():
                self._advance(c, loop)

    def state(self, c, loop_id, value):
        c.execute("UPDATE loops SET state=%s,updated_at=now() WHERE id=%s", (value, loop_id))

    def _advance(self, c, loop):
        if loop["config"]["code_digest"] != code_identity():
            self.state(c, loop["id"], "BLOCKED_RELEASE_CHANGED")
            return
        active = c.execute(
            "SELECT * FROM cycles WHERE loop_id=%s AND state!='COMPLETE' ORDER BY draw_at LIMIT 1",
            (loop["id"],),
        ).fetchone()
        if active:
            failed = c.execute(
                "SELECT error_code FROM jobs WHERE cycle_id=%s AND state='FAILED' LIMIT 1", (active["id"],)
            ).fetchone()
            self.state(c, loop["id"], f"BLOCKED_{failed['error_code']}" if failed else active["state"])
            if active["state"] == "EVALUATE":
                label = c.execute(
                    "SELECT 1 FROM effective_draws WHERE issue=%s AND available_at<=%s",
                    (active["issue"], now()),
                ).fetchone()
                if loop["mode"] == "REPLAY" or label:
                    self.add_job(c, active["id"], "EVALUATE")
                else:
                    self.state(c, loop["id"], "WAITING_FOR_LABEL")
            return
        if loop["id"] == "mail-forward" or loop["config"].get("externally_sealed"):
            self.state(c, loop["id"], "WAITING_18_50_VALIDATED_SEAL")
            return
        completed = c.execute(
            "SELECT * FROM cycles WHERE loop_id=%s ORDER BY draw_at DESC,created_at DESC LIMIT 1",
            (loop["id"],),
        ).fetchone()
        count = c.execute("SELECT count(*) AS n FROM cycles WHERE loop_id=%s", (loop["id"],)).fetchone()["n"]
        if count >= loop["config"]["max_cycles"]:
            self.state(c, loop["id"], "PAUSED_CYCLE_BUDGET")
            return
        if loop["mode"] == "REPLAY":
            rows = c.execute("SELECT issue,draw_at FROM draws ORDER BY draw_at,issue").fetchall()
            candidates = rows[loop["config"]["bootstrap"] :]
            target = next(
                (r for r in candidates if not completed or r["draw_at"] > completed["draw_at"]), None
            )
            if target is None:
                self._refit_or_wait(c, loop, completed, "WAITING_FOR_DATA")
                return
            cutoff = target["draw_at"] - timedelta(microseconds=1)
        else:
            target = c.execute(
                """SELECT t.* FROM targets t WHERE t.deadline>now()
                AND NOT EXISTS(SELECT 1 FROM cycles cy WHERE cy.loop_id=%s AND cy.issue=t.issue)
                AND NOT EXISTS(SELECT 1 FROM draws d WHERE d.issue=t.issue)
                ORDER BY t.draw_at LIMIT 1""",
                (loop["id"],),
            ).fetchone()
            if target is None:
                self._refit_or_wait(c, loop, completed, "WAITING_FOR_TARGET_SCHEDULE")
                return
            cutoff = now()
        dataset = self.data.snapshot(c, cutoff=cutoff, target_draw_at=target["draw_at"], mode=loop["mode"])
        if dataset["sample_count"] < loop["config"]["bootstrap"]:
            self.state(c, loop["id"], "WAITING_FOR_HISTORY")
            return
        cycle_id = digest([loop["id"], target["issue"]])
        c.execute(
            """INSERT INTO cycles(id,loop_id,issue,draw_at,cutoff,dataset_id,parent_model_id)
            VALUES(%s,%s,%s,%s,%s,%s,%s)""",
            (
                cycle_id,
                loop["id"],
                target["issue"],
                target["draw_at"],
                cutoff,
                dataset["id"],
                completed["model_id"] if completed else None,
            ),
        )
        self.add_job(c, cycle_id, "TRAIN")
        self.state(c, loop["id"], "TRAIN")

    def _refit_or_wait(self, c, loop, parent, waiting_state):
        latest = c.execute("""SELECT issue,draw_at FROM effective_draws WHERE available_at<=now()
            AND observed_at<=now() ORDER BY draw_at DESC LIMIT 1""").fetchone()
        if latest is None:
            self.state(c, loop["id"], waiting_state)
            return
        learned = c.execute(
            """SELECT 1 FROM models m JOIN cycles cy ON cy.id=m.cycle_id
            WHERE cy.loop_id=%s AND m.manifest->>'through_issue'=%s LIMIT 1""",
            (loop["id"], latest["issue"]),
        ).fetchone()
        if learned:
            self.state(c, loop["id"], waiting_state)
            return
        # Learning new labels must not depend on knowing the next draw's schedule.
        cutoff = now()
        dataset = self.data.snapshot(c, cutoff=cutoff, target_draw_at=cutoff, mode=loop["mode"])
        if dataset["sample_count"] < loop["config"]["bootstrap"]:
            self.state(c, loop["id"], "WAITING_FOR_HISTORY")
            return
        cycle_id = digest([loop["id"], latest["issue"], "REFIT"])
        c.execute(
            """INSERT INTO cycles(id,loop_id,issue,purpose,draw_at,cutoff,dataset_id,parent_model_id)
            VALUES(%s,%s,%s,'REFIT',%s,%s,%s,%s)""",
            (
                cycle_id,
                loop["id"],
                latest["issue"],
                latest["draw_at"],
                cutoff,
                dataset["id"],
                parent["model_id"] if parent else None,
            ),
        )
        self.add_job(c, cycle_id, "TRAIN")
        self.state(c, loop["id"], "LEARNING_NEW_LABELS")
