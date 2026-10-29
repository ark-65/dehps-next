from datetime import timedelta

from psycopg.types.json import Jsonb

from .domain import digest, evaluate, now
from .errors import DomainError
from .model import Recipe, predict, train
from .scheduler import Scheduler


class Pipeline:
    def __init__(self, db, artifacts):
        self.db, self.artifacts = db, artifacts

    def context(self, job):
        return self.db.rows(
            """SELECT cy.*,l.mode,l.config,ds.artifact AS dataset_artifact
            FROM cycles cy JOIN loops l ON cy.loop_id=l.id JOIN datasets ds ON cy.dataset_id=ds.id
            WHERE cy.id=%s""",
            (job["cycle_id"],),
        )[0]

    def execute(self, job, pulse):
        context = self.context(job)
        {"TRAIN": self.training, "SEAL": self.sealing, "EVALUATE": self.evaluating}[job["kind"]](
            job, context, pulse
        )

    def training(self, job, context, pulse):
        recipe = Recipe(**context["config"]["recipe"])
        snapshot = self.artifacts.read(context["dataset_artifact"])
        parent_bytes, parent_labels = None, set()
        if context["parent_model_id"]:
            parent = self.db.rows("SELECT * FROM models WHERE id=%s", (context["parent_model_id"],))[0]
            if parent["manifest"]["recipe"] != recipe.__dict__:
                raise DomainError("PARENT_RECIPE_CHANGED", "Warm start requires identical recipe")
            parent_bytes = self.artifacts.read(parent["artifact"])
            parent_labels = set(parent["manifest"]["label_issues"])

        def save_checkpoint(data, epoch):
            pulse()
            self.db.heartbeat(job)
            ref = self.artifacts.write(
                data, category="checkpoints", key=f"{job['id']}-{job['token']}-{(epoch // 5) % 2}.pt"
            )
            self.db.checkpoint(job, ref)

        checkpoint = self.artifacts.read(job["checkpoint"]) if job["checkpoint"] else None
        data, manifest = train(snapshot, recipe, parent_bytes, checkpoint, save_checkpoint, pulse)
        manifest["purpose"] = context["purpose"]
        manifest["code_digest"] = context["config"]["code_digest"]
        pulse()
        ref = self.artifacts.write(data, category="models")
        model_id = ref["sha256"]
        with self.db.pool.connection() as c, c.transaction():
            self.db.fence(c, job)
            c.execute(
                """INSERT INTO models(id,cycle_id,parent_id,dataset_id,artifact,manifest)
                VALUES(%s,%s,%s,%s,%s,%s)""",
                (
                    model_id,
                    context["id"],
                    context["parent_model_id"],
                    context["dataset_id"],
                    Jsonb(ref),
                    Jsonb(manifest),
                ),
            )
            for issue in manifest["label_issues"]:
                c.execute(
                    "INSERT INTO consumptions VALUES(%s,%s,%s,%s)",
                    (model_id, issue, recipe.epochs, issue not in parent_labels),
                )
            next_state = "COMPLETE" if context["purpose"] == "REFIT" else "SEAL"
            c.execute(
                "UPDATE cycles SET state=%s,model_id=%s WHERE id=%s", (next_state, model_id, context["id"])
            )
            if context["purpose"] == "PREDICT":
                Scheduler.add_job(c, context["id"], "SEAL")
            self.db.complete(c, job)
            c.execute("UPDATE jobs SET checkpoint=NULL WHERE id=%s", (job["id"],))
        self.artifacts.cleanup_checkpoints(job["id"])

    def sealing(self, job, context, pulse):
        model = self.db.rows("SELECT * FROM models WHERE id=%s", (context["model_id"],))[0]
        prediction, baseline = predict(
            self.artifacts.read(model["artifact"]),
            self.artifacts.read(context["dataset_artifact"]),
            Recipe(**context["config"]["recipe"]),
        )
        pulse()
        with self.db.pool.connection() as c, c.transaction():
            self.db.fence(c, job)
            if context["mode"] == "FORWARD":
                target = c.execute("SELECT * FROM targets WHERE issue=%s", (context["issue"],)).fetchone()
                if (
                    now() >= target["deadline"]
                    or c.execute("SELECT 1 FROM draws WHERE issue=%s", (context["issue"],)).fetchone()
                ):
                    raise DomainError("MISSED_DEADLINE", "Cannot seal a late or already-known prediction")
            c.execute(
                """INSERT INTO predictions(cycle_id,model_id,issue,mode,cutoff,payload,
                payload_digest,baseline) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    context["id"],
                    model["id"],
                    context["issue"],
                    context["mode"],
                    context["cutoff"],
                    Jsonb(prediction),
                    digest(prediction),
                    Jsonb(baseline),
                ),
            )
            c.execute("UPDATE cycles SET state='EVALUATE' WHERE id=%s", (context["id"],))
            self.db.complete(c, job)

    def evaluating(self, job, context, pulse):
        prediction = self.db.rows("SELECT * FROM predictions WHERE cycle_id=%s", (context["id"],))[0]
        actuals = self.db.rows("SELECT * FROM draws WHERE issue=%s", (context["issue"],))
        if not actuals:
            raise DomainError("LABEL_NOT_AVAILABLE", "Draw has not been ingested")
        actual = actuals[0]
        if context["mode"] == "FORWARD":
            if actual["available_at"] > now() or actual["draw_at"] > now():
                raise DomainError("LABEL_NOT_AVAILABLE", "Draw is not yet available")
            target = self.db.rows("SELECT * FROM targets WHERE issue=%s", (context["issue"],))[0]
            if prediction["sealed_at"] >= target["deadline"]:
                raise DomainError("LATE_PREDICTION", "Prediction missed its pre-draw deadline")
            # Date-only official receipts must agree with the registered local draw day.
            if (
                abs((actual["draw_at"] - target["draw_at"]).total_seconds())
                > timedelta(days=1).total_seconds()
            ):
                raise DomainError("TARGET_DATE_CONFLICT", "Registered draw date differs from official data")
        metrics = evaluate(prediction["payload"], actual, prediction["baseline"])
        pulse()
        with self.db.pool.connection() as c, c.transaction():
            self.db.fence(c, job)
            c.execute(
                "INSERT INTO evaluations(cycle_id,issue,mode,metrics) VALUES(%s,%s,%s,%s)",
                (context["id"], context["issue"], context["mode"], Jsonb(metrics)),
            )
            c.execute("UPDATE cycles SET state='COMPLETE' WHERE id=%s", (context["id"],))
            self.db.complete(c, job)
