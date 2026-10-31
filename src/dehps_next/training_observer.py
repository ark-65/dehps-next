"""Restart-safe finite observation; never equate an enabled observer with a passed soak."""

from datetime import timedelta

from psycopg.types.json import Jsonb

from .domain import now
from .errors import DomainError
from .research_memory import progress_status
from .training_window import status as training_window


def start(db, name, hours=24, interval=300):
    if not name or len(name) > 80 or not 1 <= hours <= 168 or not 30 <= interval <= 3600:
        raise DomainError("SOAK_POLICY", "Expected a named1..168h observation,30..3600s sampling")
    with db.pool.connection() as c:
        c.execute(
            """INSERT INTO research_soaks(id,deadline,interval_seconds)
            VALUES(%s,now()+(%s*interval '1 hour'),%s) ON CONFLICT(id) DO NOTHING""",
            (name, hours, interval),
        )
        return c.execute("SELECT * FROM research_soaks WHERE id=%s", (name,)).fetchone()


def sample_due(db):
    with db.pool.connection() as c, c.transaction():
        runs = c.execute("""SELECT * FROM research_soaks WHERE state='RUNNING'
            AND next_sample<=now() ORDER BY started_at FOR UPDATE SKIP LOCKED""").fetchall()
        for run in runs:
            clock = now()
            window = training_window(c)
            progress = progress_status(db, since=run["started_at"])
            last_fit = progress["last_actual_fit_at"]
            progress["last_actual_fit_at"] = last_fit.isoformat() if last_fit else None
            programs = c.execute("""SELECT id,state,current_campaign,last_reason FROM research_programs
                WHERE state!='DISABLED' ORDER BY id""").fetchall()
            jobs = c.execute(
                "SELECT kind,state,count(*) AS n FROM jobs WHERE state IN ('READY','RUNNING') GROUP BY kind,state"
            ).fetchall()
            stalled = (
                not window["paused"]
                and programs
                and (clock - (last_fit or run["started_at"])).total_seconds() > 900
            )
            overlap = c.execute(
                """SELECT count(DISTINCT m.id) AS calls FROM research_model_calls m
                JOIN attempts a ON a.started_at<m.created_at+(m.metrics->>'wall_seconds')::double precision*interval '1 second'
                  AND a.ended_at>m.created_at
                JOIN jobs j ON j.id=a.job_id JOIN research_nodes n ON n.id=j.research_node_id
                WHERE m.state='SUCCEEDED' AND m.created_at>=%s AND j.kind='RESEARCH_EVALUATE'
                  AND a.state='SUCCEEDED'
                  AND (n.evaluation->'execution'->>'origin_fits_executed_this_attempt')::int>0""",
                (clock - timedelta(seconds=run["interval_seconds"]),),
            ).fetchone()["calls"]
            payload = {
                "window": window,
                "progress": progress,
                "programs": programs,
                "jobs": jobs,
                "cpu_gpu_overlapping_calls_this_interval": overlap,
                "review_required": bool(stalled),
                "mail_delivery": c.execute(
                    "SELECT state,count(*) AS n FROM mail_deliveries GROUP BY state"
                ).fetchall(),
                "memory": c.execute(
                    "SELECT contract,version,cursor FROM research_memory_heads ORDER BY contract"
                ).fetchall(),
                "scope": "OBSERVATION;NOT_PREDICTIVE_OR_MAIL_DELIVERY_PROOF",
            }
            previous = c.execute(
                "SELECT max(sample_at) AS at FROM research_soak_samples WHERE soak_id=%s", (run["id"],)
            ).fetchone()["at"]
            gap = (clock - (previous or run["started_at"])).total_seconds()
            c.execute(
                "INSERT INTO research_soak_samples VALUES(%s,%s,%s)", (run["id"], clock, Jsonb(payload))
            )
            maximum = max(run["max_gap_seconds"], gap)
            state = "RUNNING"
            if clock >= run["deadline"]:
                warnings = c.execute(
                    "SELECT count(*) AS n FROM research_soak_samples WHERE soak_id=%s AND (payload->>'review_required')::boolean",
                    (run["id"],),
                ).fetchone()["n"]
                state = (
                    "REVIEW_REQUIRED"
                    if warnings or maximum > run["interval_seconds"] * 2
                    else "OBSERVED_COMPLETE"
                )
            c.execute(
                """UPDATE research_soaks SET next_sample=%s,max_gap_seconds=%s,state=%s,
                finished_at=CASE WHEN %s='RUNNING' THEN NULL ELSE %s END WHERE id=%s""",
                (clock + timedelta(seconds=run["interval_seconds"]), maximum, state, state, clock, run["id"]),
            )
    return len(runs)
