"""Hardware admission and bounded writes; local usage is neither billing nor a quota."""

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from .domain import now
from .errors import DomainError

ZONE = ZoneInfo("Asia/Shanghai")
GIB = 1024**3
TRAINING_CPUS = 8
COMPUTE_WALL = 120
TERMINAL = ("BATCH_COMPLETE", "BUDGET_EXHAUSTED", "COMPLETE", "SUPERSEDED", "SEARCH_EXHAUSTED")


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
        raise DomainError(
            "LOCAL_USAGE_NOT_QUOTA",
            "Local use is observed as tokens only; configure hardware safeguards instead of usage quotas",
        )

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
        c.execute(
            "UPDATE resource_days SET reserved=greatest(0,reserved-%s) WHERE day=%s",
            (r["cpu_reserved"], r["day"]),
        )
        c.execute(
            """UPDATE resource_reservations SET state=%s,charged=%s,wall_seconds=%s,
            process_cpu_seconds=%s,ended_at=now() WHERE token=%s AND state='ACTIVE'""",
            (state, None, wall, process_cpu, r["token"]),
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
        wall, cpu, write = (
            (420, 5, 4 * 1024**2) if lane == "planning" else (COMPUTE_WALL, TRAINING_CPUS, 32 * 1024**2)
        )
        if lane == "planning" and not closing:
            from .research_agent import use_local_model

            campaign = c.execute(
                "SELECT r.* FROM research_campaigns r JOIN research_nodes n ON n.campaign_id=r.id WHERE n.id=%s",
                (job["research_node_id"],),
            ).fetchone()
            nodes = c.execute(
                "SELECT id FROM research_nodes WHERE campaign_id=%s", (campaign["id"],)
            ).fetchall()
            if campaign["config"]["planner"] != "local" or not use_local_model(self.db, campaign, nodes):
                wall, cpu = 30, 1
        if closing:
            wall, cpu, write = 5, 1, 64 * 1024
        if not research:
            wall, cpu, write = 600, TRAINING_CPUS, 64 * 1024**2
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
        # No daily capacity/token/call admission limit for local work. Hardware lanes and writes stay bounded.
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
        c.execute(
            "INSERT INTO resource_state VALUES(1,%s) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
            (Jsonb({"reason": "ADMITTED", "job": job["id"], "at": now().isoformat()}),),
        )
        # Core work keeps its priority and hardware lane; no usage allowance is enforced.
        stored_lane = lane if research else "core_" + lane
        amount = 0  # Historical CPU charging retired; per-job CPU and wall metrics remain observability only.
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
