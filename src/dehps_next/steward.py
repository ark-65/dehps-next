"""Durable automatic topic succession with explicit novelty, time and daily budgets."""

from psycopg.types.json import Jsonb

from .data import DataService
from .domain import digest, now
from .errors import DomainError
from .lifecycle import Lifecycle
from .release import code_identity
from .research import Research
from .resources import TERMINAL, ZONE, Resources

TOPICS = [
    {
        "name": "spectral-locality",
        "methods": ["fft", "ridge"],
        "question": "Can local spectral smoothing reduce variance without harming blue calibration?",
    },
    {
        "name": "calibration-stability",
        "methods": ["newton", "ridge"],
        "question": "Can prior-only calibration or shrinkage correct overconfidence seen in prior failed branches?",
    },
    {
        "name": "regularized-history",
        "methods": ["ridge", "fft", "newton"],
        "question": "Which representation and shrinkage survives recent versus dispersed historical checks?",
    },
]


class Steward:
    def __init__(self, db, artifacts):
        self.db, self.artifacts = db, artifacts
        self.resources = Resources(db)

    def enable(self, name, *, interval=1800, max_daily=3, max_nodes=3, planner="local"):
        if (
            not name
            or len(name) > 40
            or not 10 <= interval <= 86400
            or not 1 <= max_daily <= 3
            or not 2 <= max_nodes <= 4
            or planner not in ("rules", "local")
        ):
            raise DomainError("PROGRAM_POLICY", "Invalid bounded program policy")
        config = {
            "interval": interval,
            "max_daily": max_daily,
            "max_nodes": max_nodes,
            "planner": planner,
            "code_digest": code_identity(),
            "topics": TOPICS,
            "scope": "DEVELOPMENT_ONLY",
        }
        with self.db.pool.connection() as c:
            old = c.execute("SELECT config FROM research_programs WHERE id=%s", (name,)).fetchone()
            if old and old["config"] != config:
                raise DomainError("PROGRAM_POLICY_CONFLICT", "Program policy cannot change silently")
            c.execute(
                "INSERT INTO research_programs(id,config) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                (name, Jsonb(config)),
            )
        return {"id": name, "config": config}

    def tick(self):
        output = []
        with self.db.pool.connection() as c, c.transaction():
            if not c.execute("SELECT pg_try_advisory_xact_lock(740141) AS locked").fetchone()["locked"]:
                return []
            for program in c.execute(
                "SELECT * FROM research_programs WHERE state!='DISABLED' ORDER BY created_at FOR NO KEY UPDATE"
            ).fetchall():
                state, reason = self.advance(c, program)
                c.execute(
                    "UPDATE research_programs SET state=%s,last_reason=%s,updated_at=now() WHERE id=%s AND (state,last_reason) IS DISTINCT FROM (%s,%s)",
                    (state, reason, program["id"], state, reason),
                )
                output.append({"program": program["id"], "state": state, "reason": reason})
        return output

    def advance(self, c, p):
        config = p["config"]
        if config["code_digest"] != code_identity():
            return (
                "BLOCKED_RELEASE_CHANGED",
                "Explicitly review and re-register program policy after a release",
            )
        day = now().astimezone(ZONE).date()
        current = (
            c.execute("SELECT * FROM research_campaigns WHERE id=%s", (p["current_campaign"],)).fetchone()
            if p["current_campaign"]
            else None
        )
        if current and current["status"] not in TERMINAL and not current["status"].startswith("BLOCKED_"):
            return "RUNNING", current["id"]
        if current:
            completed = list(p["completed"])
            if current["identity"] not in completed:
                completed.append(current["identity"])
                champion = c.execute(
                    "SELECT spec FROM research_nodes WHERE id=%s", (current["selected_node"],)
                ).fetchone()
                c.execute(
                    "UPDATE research_programs SET completed=%s,champion_spec=%s,current_campaign=NULL,next_due=now()+(%s*interval '1 second') WHERE id=%s",
                    (
                        Jsonb(completed[-16:]),
                        Jsonb(champion["spec"]) if champion else None,
                        config["interval"],
                        p["id"],
                    ),
                )
                return "COOLDOWN", current["status"]
        if p["next_due"] > now():
            return "COOLDOWN", p["next_due"].isoformat()
        if p["launch_day"] == day and p["launched_today"] >= config["max_daily"]:
            return "WAITING_DAILY_BUDGET", "Campaign count resets at Asia/Shanghai midnight"
        today = c.execute("SELECT * FROM resource_days WHERE day=%s", (day,)).fetchone()
        policy = Resources.policy(c)
        if (
            (
                today
                and (
                    today["spent"] + today["reserved"] + 240 > policy["capacity"]
                    or today["calls"] + 2 > policy["calls"]
                )
            )
            or policy["capacity"] < 240
            or policy["calls"] < 2
        ):
            return "WAITING_DAILY_BUDGET", "Capacity seconds or local model-call allowance exhausted"
        try:
            reason = self.resources.pressure()
        except DomainError as exc:
            reason = exc.code
        if reason:
            return "WAITING_RESOURCES", reason
        dataset = DataService(self.db, self.artifacts).research_snapshot(c)
        completed = p["completed"] if dataset["id"] == p["last_dataset"] else []
        for topic in config["topics"]:
            identity = digest([config["code_digest"], dataset["id"], topic["name"]])
            if (
                identity not in completed
                and not c.execute(
                    "SELECT 1 FROM research_campaigns WHERE program_id=%s AND identity=%s",
                    (p["id"], identity),
                ).fetchone()
            ):
                break
        else:
            return (
                "WAITING_NEW_DATA",
                "All registered questions for this snapshot exhausted; no repeated roots",
            )
        generation = p["generation"] + 1
        name = f"{p['id']}-{generation}-{identity[:8]}"
        Research(self.db, self.artifacts).create(
            name,
            planner=config["planner"],
            max_nodes=config["max_nodes"],
            root_spec=p["champion_spec"],
            topic=topic,
            program_id=p["id"],
            launch_identity=identity,
            connection=c,
        )
        c.execute(
            """UPDATE research_programs SET generation=%s,current_campaign=%s,last_dataset=%s,completed=%s,
            launched_today=CASE WHEN launch_day=%s THEN launched_today+1 ELSE 1 END,launch_day=%s WHERE id=%s""",
            (generation, name, dataset["id"], Jsonb(completed), day, day, p["id"]),
        )
        return "RUNNING", name

    def maintain(self):
        with self.db.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(740140)")
            self.resources.reap(c)
        preview = Lifecycle(self.db, self.artifacts).collect(apply=False)
        # Always preview the current reachability before the automatic sweep.
        sweep = Lifecycle(self.db, self.artifacts).collect(apply=True)
        return {"gc_preview": preview, "gc": sweep, "programs": self.tick()}
