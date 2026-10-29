"""Atomic admission, bounded write reservations and conservative capacity-second accounting."""

import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from .domain import now
from .errors import DomainError

ZONE = ZoneInfo("Asia/Shanghai")
GIB = 1024**3
DAILY_CAPACITY = 7200  # CPU quota * elapsed seconds, an upper bound, not measured CPU time.
DAILY_CALLS = 24
TERMINAL = ("BUDGET_EXHAUSTED", "COMPLETE", "SUPERSEDED", "SEARCH_EXHAUSTED")


class Resources:
    def __init__(self, db):
        self.db = db
        if not hasattr(db, "artifacts"):
            from .artifacts import Artifacts

            db.artifacts = Artifacts(db.settings, db)

    @staticmethod
    def policy(c):
        return c.execute("SELECT * FROM resource_policy WHERE id=1").fetchone()

    def set_policy(self, capacity, calls, reason):
        if not 0 <= capacity <= DAILY_CAPACITY or not 0 <= calls <= DAILY_CALLS or len(reason) < 12:
            raise DomainError(
                "BUDGET_POLICY", "Operator policy may lower accepted ceilings; record a concrete reason"
            )
        with self.db.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(740140)")
            c.execute("UPDATE resource_policy SET capacity=%s,calls=%s WHERE id=1", (capacity, calls))
            c.execute(
                "INSERT INTO resource_policy_changes(policy,reason) VALUES(%s,%s)",
                (Jsonb({"capacity": capacity, "calls": calls}), reason),
            )
            c.execute(
                "DELETE FROM resource_policy_changes WHERE id IN (SELECT id FROM resource_policy_changes ORDER BY id DESC OFFSET 128)"
            )
        return {"capacity": capacity, "calls": calls, "reason": reason}

    def telemetry(self):
        path = self.db.settings.runtime.parent / "host" / "telemetry.json"
        try:
            value = json.loads(path.read_text())
            if (
                value["owner"] != "dehps-next"
                or (now() - datetime.fromisoformat(value["at"])).total_seconds() > 90
            ):
                raise ValueError("stale")
            return value
        except (OSError, ValueError, KeyError):
            raise DomainError(
                "HOST_TELEMETRY_UNAVAILABLE", "Fresh Next-only host telemetry required"
            ) from None

    def pressure(self):
        t = self.telemetry()
        if not t.get("complete"):
            return "HOST_ACCOUNTING_INCOMPLETE"
        if t["disk_free"] < max(20 * GIB, t["disk_total"] * 0.05):
            return "HOST_LOW_DISK"
        if t["owned_upper_bytes"] >= 85 * GIB:
            return "NEXT_HIGH_WATER"
        limits = {
            "database": 10 * GIB,
            "environment": 20 * GIB,
            "inference": 8 * GIB,
            "staging": 7 * GIB,
            "logs": 3 * GIB,
            "backups": 10 * GIB,
        }
        if any(t["categories"][key] >= limit for key, limit in limits.items()):
            return "CATEGORY_STORAGE_LIMIT"
        # All compute/planning/inference quotas fit under both physical and available memory envelopes.
        if 9 * GIB > min(t["memory_total"] * 0.6, t["memory_available"] - 4 * GIB):
            return "HOST_MEMORY_PRESSURE"
        return None

    @staticmethod
    def settle(c, reservation, wall, process_cpu=0, state="SETTLED", full=False):
        r = reservation
        if r["state"] != "ACTIVE":
            return
        wall = min(r["wall_cap"], max(0, wall))
        charge = r["cpu_reserved"] if full else min(r["cpu_reserved"], wall * r["cpu_cap"])
        c.execute(
            "UPDATE resource_days SET reserved=greatest(0,reserved-%s) WHERE day=%s",
            (r["cpu_reserved"], r["day"]),
        )
        start = r["created_at"].astimezone(ZONE)
        end = start + timedelta(seconds=(r["wall_cap"] if full else wall))
        cursor = start
        while cursor < end and r["cpu_reserved"]:
            boundary = datetime.combine(cursor.date() + timedelta(days=1), datetime.min.time(), ZONE)
            stop = min(end, boundary)
            portion = (stop - cursor).total_seconds() * r["cpu_cap"]
            c.execute(
                "INSERT INTO resource_days(day,spent) VALUES(%s,%s) ON CONFLICT(day) DO UPDATE SET spent=resource_days.spent+excluded.spent",
                (cursor.date(), portion),
            )
            cursor = stop
        c.execute(
            """UPDATE resource_reservations SET state=%s,charged=%s,wall_seconds=%s,
            process_cpu_seconds=%s,ended_at=now() WHERE token=%s AND state='ACTIVE'""",
            (state, charge, wall, process_cpu, r["token"]),
        )

    def reap(self, c):
        for r in c.execute("""SELECT r.* FROM resource_reservations r LEFT JOIN jobs j ON j.token=r.token
            WHERE r.state='ACTIVE' AND (j.id IS NULL OR (j.state!='RUNNING' AND j.updated_at<now()-interval '60 seconds') OR j.lease_until<now()) FOR UPDATE OF r""").fetchall():
            self.settle(c, r, r["wall_cap"], state="EXPIRED_CHARGED_FULL", full=True)

    def admit(self, c, job, token):
        c.execute("SELECT pg_advisory_xact_lock(740140)")
        self.reap(c)
        research = job["research_node_id"] is not None
        closing = False
        if job["kind"] == "RESEARCH_PLAN":
            closing = c.execute(
                """SELECT count(n2.id)>=(r.config->>'max_nodes')::int AS closing
                FROM research_nodes n JOIN research_campaigns r ON r.id=n.campaign_id
                JOIN research_nodes n2 ON n2.campaign_id=r.id WHERE n.id=%s GROUP BY r.config""",
                (job["research_node_id"],),
            ).fetchone()["closing"]
        lane = "planning" if job["kind"] == "RESEARCH_PLAN" else "compute"
        wall, cpu, write = (150, 5, 4 * 1024**2) if lane == "planning" else (120, 2, 32 * 1024**2)
        if closing:
            wall, cpu, write = 5, 1, 64 * 1024
        if not research:
            wall, cpu, write = 600, 2, 64 * 1024**2
        reason = None
        lifetime = c.execute(
            "SELECT coalesce(sum(wall_seconds),0) AS n FROM resource_reservations WHERE job_id=%s AND state!='ACTIVE'",
            (job["id"],),
        ).fetchone()["n"]
        if research and not closing and lifetime >= 600:
            c.execute(
                "UPDATE jobs SET state='FAILED',error_code='RESEARCH_LIFETIME_BUDGET' WHERE id=%s",
                (job["id"],),
            )
            return None
        if c.execute(
            "SELECT 1 FROM resource_reservations WHERE state='ACTIVE' AND replace(lane,'core_','')=%s",
            (lane,),
        ).fetchone():
            reason = "WAITING_LANE"
        if research and not closing:
            try:
                reason = reason or self.pressure()
            except DomainError as exc:
                reason = exc.code
        day = now().astimezone(ZONE).date()
        c.execute("INSERT INTO resource_days(day) VALUES(%s) ON CONFLICT DO NOTHING", (day,))
        spent = c.execute("SELECT * FROM resource_days WHERE day=%s FOR UPDATE", (day,)).fetchone()
        policy = self.policy(c)
        active = c.execute(
            "SELECT coalesce(sum(cpu_reserved),0) AS n FROM resource_reservations WHERE state='ACTIVE' AND lane NOT LIKE 'core%%'"
        ).fetchone()["n"]
        if research and not closing and spent["spent"] + active + wall * cpu > policy["capacity"]:
            reason = reason or "WAITING_DAILY_CAPACITY"
        if research and lane == "planning" and not closing and spent["calls"] + 2 > policy["calls"]:
            reason = reason or "WAITING_DAILY_MODEL_CALLS"
        pending = c.execute(
            "SELECT coalesce(sum(greatest(0,write_reserved-written)),0) AS n FROM resource_reservations WHERE state='ACTIVE'"
        ).fetchone()["n"]
        if self.db.artifacts.usage() + pending + write > self.db.settings.quota_bytes:
            reason = reason or "WAITING_WRITE_RESERVATION"
        if reason:
            c.execute(
                "INSERT INTO resource_state VALUES(1,%s) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                (Jsonb({"reason": reason, "job": job["id"], "at": now().isoformat()}),),
            )
            return None
        # Core charges are tracked separately and do not consume the research allowance.
        stored_lane = lane if research else "core_" + lane
        amount = wall * cpu if research and not closing else 0
        c.execute(
            """INSERT INTO resource_reservations(token,job_id,day,lane,cpu_cap,wall_cap,cpu_reserved,write_reserved)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
            (token, job["id"], day, stored_lane, cpu, wall, amount, write),
        )
        c.execute("UPDATE resource_days SET reserved=reserved+%s WHERE day=%s", (amount, day))
        return {"wall_cap": wall, "write_cap": write}

    def finish(self, token, wall, process_cpu):
        with self.db.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(740140)")
            r = c.execute(
                "SELECT * FROM resource_reservations WHERE token=%s FOR UPDATE", (token,)
            ).fetchone()
            if r:
                self.settle(c, r, wall, process_cpu)

    def model_call(self, c):
        day = now().astimezone(ZONE).date()
        c.execute("INSERT INTO resource_days(day) VALUES(%s) ON CONFLICT DO NOTHING", (day,))
        if not c.execute(
            "UPDATE resource_days SET calls=calls+1 WHERE day=%s AND calls<%s RETURNING day",
            (day, self.policy(c)["calls"]),
        ).fetchone():
            raise DomainError("YIELD_MODEL_CALL_BUDGET", "Resume after the local-day call budget resets")
