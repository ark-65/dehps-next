import uuid
from importlib.resources import files

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from .errors import LeaseLost


class Database:
    def __init__(self, settings):
        self.settings = settings
        self.pool = ConnectionPool(
            settings.database_url,
            open=True,
            min_size=1,
            max_size=4,
            timeout=10,
            kwargs={
                "autocommit": True,
                "row_factory": dict_row,
                "options": "-c statement_timeout=15000 -c lock_timeout=3000",
            },
        )
        self.pool.wait()

    def close(self):
        self.pool.close()

    def migrate(self):
        with self.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(740131)")
            c.execute("CREATE TABLE IF NOT EXISTS schema_migrations(version integer PRIMARY KEY)")
            if not c.execute("SELECT 1 FROM schema_migrations WHERE version=1").fetchone():
                c.execute(files("dehps_next").joinpath("migrations/001_up.sql").read_text())
                c.execute("INSERT INTO schema_migrations VALUES(1)")
            if not c.execute("SELECT 1 FROM schema_migrations WHERE version=2").fetchone():
                c.execute(files("dehps_next").joinpath("migrations/002_up.sql").read_text())
                c.execute("INSERT INTO schema_migrations VALUES(2)")
            if not c.execute("SELECT 1 FROM schema_migrations WHERE version=3").fetchone():
                c.execute(files("dehps_next").joinpath("migrations/003_up.sql").read_text())
                c.execute("INSERT INTO schema_migrations VALUES(3)")
            if not c.execute("SELECT 1 FROM schema_migrations WHERE version=4").fetchone():
                c.execute(files("dehps_next").joinpath("migrations/004_up.sql").read_text())
                c.execute("INSERT INTO schema_migrations VALUES(4)")
            if not c.execute("SELECT 1 FROM schema_migrations WHERE version=5").fetchone():
                c.execute(files("dehps_next").joinpath("migrations/005_up.sql").read_text())
                c.execute("INSERT INTO schema_migrations VALUES(5)")
            if not c.execute("SELECT 1 FROM schema_migrations WHERE version=6").fetchone():
                c.execute(files("dehps_next").joinpath("migrations/006_up.sql").read_text())
                c.execute("INSERT INTO schema_migrations VALUES(6)")

    def rows(self, sql, params=()):
        with self.pool.connection() as c:
            return c.execute(sql, params).fetchall()

    def claim(self, worker, role="all"):
        token = str(uuid.uuid4())
        with self.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(740139)")
            c.execute("""UPDATE attempts SET state='LOST', ended_at=now()
                WHERE state='RUNNING' AND id IN
                (SELECT token FROM jobs WHERE state='RUNNING' AND lease_until<now())""")
            c.execute("""UPDATE jobs SET state=CASE WHEN failures+1>=3 THEN 'FAILED' ELSE 'READY' END,
                failures=failures+1,error_code='LEASE_EXPIRED', updated_at=now() WHERE state='RUNNING' AND lease_until<now()""")
            roles = {"all": "TRUE", "compute": "kind!='RESEARCH_PLAN'", "planning": "kind='RESEARCH_PLAN'"}
            if role not in roles:
                raise ValueError("Unknown worker role")
            row = c.execute(
                "SELECT * FROM jobs WHERE state='READY' AND not_before<=now() AND "
                + roles[role]
                + " ORDER BY CASE WHEN kind LIKE 'RESEARCH_%' THEN 1 ELSE 0 END,created_at,id "
                "FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            from .resources import Resources

            admission = Resources(self).admit(c, row, token)
            if admission is None:
                return None
            row = c.execute(
                """UPDATE jobs SET state='RUNNING',token=%s,attempts=attempts+1,
                lease_until=now()+(%s * interval '1 second'),updated_at=now() WHERE id=%s RETURNING *""",
                (token, self.settings.lease_seconds, row["id"]),
            ).fetchone()
            c.execute(
                "INSERT INTO attempts(id,job_id,state,worker) VALUES(%s,%s,'RUNNING',%s)",
                (token, row["id"], worker),
            )
            row["admission"] = admission
            return row

    def fence(self, c, job):
        c.execute("SELECT pg_advisory_xact_lock(740139)")
        if not c.execute(
            """SELECT 1 FROM jobs WHERE id=%s AND token=%s AND state='RUNNING'
            AND lease_until>now() FOR UPDATE""",
            (job["id"], job["token"]),
        ).fetchone():
            raise LeaseLost()

    def heartbeat(self, job):
        with self.pool.connection() as c:
            result = c.execute(
                """UPDATE jobs SET lease_until=now()+(%s * interval '1 second'),
                updated_at=now() WHERE id=%s AND token=%s AND state='RUNNING' AND lease_until>now()""",
                (self.settings.lease_seconds, job["id"], job["token"]),
            )
            if result.rowcount != 1:
                raise LeaseLost()

    def checkpoint(self, job, artifact):
        with self.pool.connection() as c, c.transaction():
            self.fence(c, job)
            c.execute("UPDATE jobs SET checkpoint=%s WHERE id=%s", (Jsonb(artifact), job["id"]))

    def complete(self, c, job):
        self.fence(c, job)
        c.execute(
            "UPDATE jobs SET state='SUCCEEDED',lease_until=NULL,updated_at=now() WHERE id=%s", (job["id"],)
        )
        c.execute("UPDATE attempts SET state='SUCCEEDED',ended_at=now() WHERE id=%s", (job["token"],))

    def fail(self, job, code):
        with self.pool.connection() as c, c.transaction():
            self.fence(c, job)
            c.execute(
                """UPDATE jobs SET state=CASE WHEN failures+1>=3 THEN 'FAILED' ELSE 'READY' END,failures=failures+1,
                error_code=%s,not_before=now()+interval '10 seconds',lease_until=NULL,updated_at=now()
                WHERE id=%s""",
                (code, job["id"]),
            )
            c.execute(
                "UPDATE attempts SET state='FAILED',error_code=%s,ended_at=now() WHERE id=%s",
                (code, job["token"]),
            )

    def defer(self, job, code, seconds=15):
        with self.pool.connection() as c, c.transaction():
            self.fence(c, job)
            c.execute(
                "UPDATE jobs SET state='READY',error_code=%s,not_before=now()+(%s*interval '1 second'),lease_until=NULL,updated_at=now() WHERE id=%s",
                (code, seconds, job["id"]),
            )
            c.execute(
                "UPDATE attempts SET state='YIELDED',error_code=%s,ended_at=now() WHERE id=%s",
                (code, job["token"]),
            )
