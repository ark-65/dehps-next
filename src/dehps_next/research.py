"""Single authoritative branch controller, dispatched through the existing leased queue."""

import json

from psycopg.types.json import Jsonb

from .data import DataService
from .domain import canonical, digest, now
from .errors import DomainError
from .release import code_identity
from .research_compute import compute_node, restore_anchor, validate_spec
from .research_protocol import make_protocol, review, summary

ROOT_SPEC = {
    "method": "raw",
    "window": 16,
    "hidden": 128,
    "epochs": 12,
    "learning_rate": 0.002,
    "weight_decay": 0.0,
    "train_history": 256,
}


class Research:
    def __init__(self, db, artifacts):
        self.db, self.artifacts = db, artifacts

    @staticmethod
    def decision(c, campaign, node, action, evidence):
        c.execute(
            "INSERT INTO research_decisions(campaign_id,node_id,action,evidence) VALUES(%s,%s,%s,%s)",
            (campaign, node, action, Jsonb(evidence)),
        )

    @staticmethod
    def job(c, node, kind):
        c.execute(
            "INSERT INTO jobs(id,research_node_id,kind) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
            (digest([node, kind]), node, kind),
        )

    def create(self, name, *, planner="rules", max_nodes=3, recent=60, historical=200):
        if planner not in ("rules", "local") or not 2 <= max_nodes <= 8 or not name or len(name) > 80:
            raise DomainError("RESEARCH_POLICY", "Invalid campaign, planner or node budget")
        config = {
            "planner": planner,
            "max_nodes": max_nodes,
            "root_spec": ROOT_SPEC,
            "code_digest": code_identity(),
            "node_seconds": 600,
            "recent": recent,
            "historical": historical,
            "max_model_calls": 8,
            "purpose": "DEVELOPMENT_RESEARCH_NOT_FORMAL_PREDICTION",
        }
        with self.db.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(740134)")
            previous = c.execute("SELECT * FROM research_campaigns WHERE id=%s", (name,)).fetchone()
            if previous:
                if previous["config"] != config:
                    raise DomainError("CAMPAIGN_CONFLICT", "Existing research config is frozen")
                return previous
            cutoff = now()
            dataset = DataService(self.db, self.artifacts).snapshot(
                c, cutoff=cutoff, target_draw_at=cutoff, mode="REPLAY"
            )
            protocol = make_protocol(dataset["sample_count"], recent, historical)
            c.execute(
                """INSERT INTO research_campaigns(id,config,dataset_id,protocol)
                VALUES(%s,%s,%s,%s)""",
                (name, Jsonb(config), dataset["id"], Jsonb(protocol)),
            )
            self._node(
                c,
                name,
                "1",
                None,
                ROOT_SPEC,
                {"hypothesis": "Frozen prior-only neural baseline", "source": "ROOT_CONTRACT"},
            )
            self.decision(
                c,
                name,
                None,
                "CAMPAIGN_FROZEN",
                {"config": config, "protocol": protocol, "dataset_id": dataset["id"]},
            )
            return {"id": name, "config": config, "protocol_digest": protocol["digest"]}

    def _node(self, c, campaign, path, parent, spec, hypothesis):
        validate_spec(spec)
        identity = digest([campaign, path])
        c.execute(
            """INSERT INTO research_nodes(id,campaign_id,path,parent_id,spec,hypothesis)
            VALUES(%s,%s,%s,%s,%s,%s)""",
            (identity, campaign, path, parent, Jsonb(spec), Jsonb(hypothesis)),
        )
        self.job(c, identity, "RESEARCH_EVALUATE")
        c.execute(
            "UPDATE research_campaigns SET status='EVALUATING',updated_at=now() WHERE id=%s", (campaign,)
        )
        return identity

    def reconcile(self):
        with self.db.pool.connection() as c, c.transaction():
            if not c.execute("SELECT pg_try_advisory_xact_lock(740134) AS locked").fetchone()["locked"]:
                return
            campaigns = c.execute(
                "SELECT * FROM research_campaigns WHERE status NOT IN ('BUDGET_EXHAUSTED','COMPLETE','SUPERSEDED')"
            ).fetchall()
            for campaign in campaigns:
                if campaign["config"]["code_digest"] != code_identity():
                    c.execute(
                        "UPDATE research_campaigns SET status='BLOCKED_RELEASE_CHANGED' WHERE id=%s",
                        (campaign["id"],),
                    )
                    continue
                failed = c.execute(
                    """SELECT n.id,j.error_code FROM research_nodes n JOIN jobs j
                    ON j.research_node_id=n.id WHERE n.campaign_id=%s AND j.state='FAILED' LIMIT 1""",
                    (campaign["id"],),
                ).fetchone()
                if failed:
                    c.execute(
                        "UPDATE research_campaigns SET status=%s WHERE id=%s",
                        ("BLOCKED_" + str(failed["error_code"]), campaign["id"]),
                    )

    def context(self, job):
        return self.db.rows(
            """SELECT n.*,r.config,r.dataset_id,r.protocol,r.selected_node,r.selected_anchor,
            ds.artifact AS dataset_artifact FROM research_nodes n
            JOIN research_campaigns r ON r.id=n.campaign_id JOIN datasets ds ON ds.id=r.dataset_id
            WHERE n.id=%s""",
            (job["research_node_id"],),
        )[0]

    def execute(self, job, pulse):
        node = self.context(job)
        if node["config"]["code_digest"] != code_identity():
            raise DomainError("RESEARCH_RELEASE_CHANGED", "Campaign must retain its accepted runtime")
        if job["kind"] == "RESEARCH_EVALUATE":
            self.evaluate(job, node, pulse)
        else:
            self.plan(job, node, pulse)

    def evaluate(self, job, node, pulse):
        snapshot = json.loads(self.artifacts.read(node["dataset_artifact"]))
        saved = json.loads(self.artifacts.read(job["checkpoint"])) if job["checkpoint"] else None
        parent = (
            self.db.rows("SELECT * FROM research_nodes WHERE id=%s", (node["parent_id"],))
            if node["parent_id"]
            else []
        )
        initial = self.artifacts.read(parent[0]["anchor"]) if parent else None

        def checkpoint(payload):
            pulse()
            self.db.heartbeat(job)
            slot = (len(payload["rows"]) // 8) % 2
            ref = self.artifacts.write(
                canonical(payload).encode(),
                category="checkpoints",
                key=f"{job['id']}-{job['token']}-{slot}.pt",
            )
            self.db.checkpoint(job, ref)

        scores, anchor_bytes, execution = compute_node(
            snapshot,
            node["spec"],
            node["protocol"],
            pulse,
            checkpoint,
            saved=saved,
            initial=initial,
            seconds=node["config"]["node_seconds"],
        )
        score_ref = self.artifacts.write(canonical(scores).encode(), category="research/scores")
        anchor_ref = self.artifacts.write(anchor_bytes, category="research/anchors")
        evaluation = {
            "scores": score_ref,
            "summary": summary(scores, node["protocol"]["origins"]),
            "protocol_digest": node["protocol"]["digest"],
            "execution": execution,
            "evidence": node["protocol"]["evidence"],
        }
        if parent:
            parent_scores = json.loads(self.artifacts.read(parent[0]["evaluation"]["scores"]))
            verdict = review(parent_scores, scores, node["protocol"])
        else:
            verdict = {"verdict": "ACCEPT_BASELINE", "protocol_digest": node["protocol"]["digest"]}
        pulse()
        with self.db.pool.connection() as c, c.transaction():
            self.db.fence(c, job)
            c.execute(
                """UPDATE research_nodes SET evaluation=%s,anchor=%s,decision=%s,status=%s,
                completed_at=now() WHERE id=%s""",
                (Jsonb(evaluation), Jsonb(anchor_ref), Jsonb(verdict), verdict["verdict"], node["id"]),
            )
            if verdict["verdict"] in ("ACCEPT_BASELINE", "ACCEPT_IMPROVEMENT"):
                c.execute(
                    """UPDATE research_campaigns SET selected_node=%s,selected_anchor=%s,
                    status='PLANNING',updated_at=now() WHERE id=%s""",
                    (node["id"], Jsonb(anchor_ref), node["campaign_id"]),
                )
                self.decision(c, node["campaign_id"], node["id"], verdict["verdict"], verdict)
            else:
                restored = restore_anchor(self.artifacts.read(parent[0]["anchor"]))
                c.execute(
                    """UPDATE research_campaigns SET selected_node=%s,selected_anchor=%s,
                    status='PLANNING',updated_at=now() WHERE id=%s""",
                    (parent[0]["id"], Jsonb(parent[0]["anchor"]), node["campaign_id"]),
                )
                self.decision(c, node["campaign_id"], node["id"], verdict["verdict"], verdict)
                self.decision(
                    c,
                    node["campaign_id"],
                    parent[0]["id"],
                    "RESTORE_PARENT",
                    {
                        "failed_or_uncertain_child": node["path"],
                        "parent_path": parent[0]["path"],
                        "restored": restored,
                        "parent_anchor": parent[0]["anchor"],
                    },
                )
            self.job(c, node["id"], "RESEARCH_PLAN")
            self.db.complete(c, job)
            c.execute("UPDATE jobs SET checkpoint=NULL WHERE id=%s", (job["id"],))
        self.artifacts.cleanup_checkpoints(job["id"])

    def plan(self, job, context, pulse):
        campaign = self.db.rows("SELECT * FROM research_campaigns WHERE id=%s", (context["campaign_id"],))[0]
        nodes = self.db.rows(
            "SELECT * FROM research_nodes WHERE campaign_id=%s ORDER BY created_at", (campaign["id"],)
        )
        if len(nodes) >= campaign["config"]["max_nodes"]:
            with self.db.pool.connection() as c, c.transaction():
                self.db.fence(c, job)
                c.execute(
                    "UPDATE research_campaigns SET status='BUDGET_EXHAUSTED',updated_at=now() WHERE id=%s",
                    (campaign["id"],),
                )
                self.decision(
                    c, campaign["id"], context["id"], "NODE_BUDGET_EXHAUSTED", {"nodes": len(nodes)}
                )
                self.db.complete(c, job)
            return
        selected = next(n for n in nodes if n["id"] == campaign["selected_node"])
        siblings = [n for n in nodes if n["parent_id"] == selected["id"]]
        spec = dict(selected["spec"])
        if campaign["config"]["planner"] == "local":
            from .research_agent import propose

            proposal = propose(campaign, nodes, pulse, self.db, self.artifacts, job)
            spec.update(proposal["spec"])
            hypothesis = proposal
        elif not siblings:
            spec["learning_rate"] = 0.05
            hypothesis = {
                "source": "BOUNDED_RULE_PLANNER",
                "hypothesis": "A more aggressive learning rate may improve adaptation",
                "falsification": "Paired recent and random historical blue loss confirms regression",
            }
        else:
            spec["learning_rate"], spec["weight_decay"] = 0.0005, 0.01
            hypothesis = {
                "source": "BOUNDED_RULE_PLANNER",
                "hypothesis": "Lower learning rate and shrinkage may reduce overfit",
                "falsification": "Same frozen validation list shows no reliable improvement",
            }
        validate_spec(spec)
        if any(n["spec"] == spec for n in nodes):
            raise DomainError("DUPLICATE_RESEARCH_DIRECTION", "Planner repeated a completed direction")
        pulse()
        with self.db.pool.connection() as c, c.transaction():
            self.db.fence(c, job)
            path = selected["path"] + "-" + str(len(siblings) + 1)
            child = self._node(c, campaign["id"], path, selected["id"], spec, hypothesis)
            self.decision(
                c,
                campaign["id"],
                child,
                "EXPLORE_NEW_DIRECTION",
                {
                    "from_path": selected["path"],
                    "to_path": path,
                    "after": context["path"],
                    "parent_anchor": selected["anchor"],
                    "hypothesis": hypothesis,
                },
            )
            self.db.complete(c, job)

    def stop_campaign(self, campaign_id, reason):
        if len(reason) < 12:
            raise DomainError("STOP_REASON_REQUIRED", "Record why this frozen campaign is superseded")
        with self.db.pool.connection() as c, c.transaction():
            campaign = c.execute(
                "SELECT * FROM research_campaigns WHERE id=%s FOR UPDATE", (campaign_id,)
            ).fetchone()
            if not campaign:
                raise DomainError("UNKNOWN_CAMPAIGN", "Campaign does not exist")
            if c.execute(
                "SELECT 1 FROM jobs j JOIN research_nodes n ON n.id=j.research_node_id WHERE n.campaign_id=%s AND j.state='RUNNING'",
                (campaign_id,),
            ).fetchone():
                raise DomainError("ACTIVE_CAMPAIGN", "Stop its active worker before superseding")
            if campaign["status"] == "SUPERSEDED":
                return {"status": "SUPERSEDED", "id": campaign_id}
            c.execute(
                "UPDATE jobs SET state='FAILED',error_code='CAMPAIGN_SUPERSEDED' WHERE research_node_id IN (SELECT id FROM research_nodes WHERE campaign_id=%s) AND state='READY'",
                (campaign_id,),
            )
            c.execute(
                "UPDATE research_campaigns SET status='SUPERSEDED',updated_at=now() WHERE id=%s",
                (campaign_id,),
            )
            self.decision(
                c,
                campaign_id,
                None,
                "CAMPAIGN_SUPERSEDED",
                {"reason": reason, "previous_status": campaign["status"], "facts_preserved": True},
            )
        return {"status": "SUPERSEDED", "id": campaign_id, "reason": reason}

    def adopt_release(self, loop_id, reason):
        if len(reason) < 12:
            raise DomainError("RELEASE_REASON_REQUIRED", "Record a concrete compatibility audit")
        with self.db.pool.connection() as c, c.transaction():
            loop = c.execute("SELECT * FROM loops WHERE id=%s FOR UPDATE", (loop_id,)).fetchone()
            if not loop:
                raise DomainError("UNKNOWN_LOOP", "Loop does not exist")
            if c.execute(
                "SELECT 1 FROM jobs j JOIN cycles cy ON cy.id=j.cycle_id WHERE cy.loop_id=%s AND j.state='RUNNING'",
                (loop_id,),
            ).fetchone():
                raise DomainError(
                    "ACTIVE_RELEASE", "Wait for the active P1 execution before adopting a release"
                )
            old = loop["config"]["code_digest"]
            if old == code_identity():
                return {"status": "already_current"}
            config = {**loop["config"], "code_digest": code_identity()}
            c.execute(
                "INSERT INTO release_adoptions(loop_id,old_digest,new_digest,reason) VALUES(%s,%s,%s,%s)",
                (loop_id, old, code_identity(), reason),
            )
            c.execute("UPDATE loops SET config=%s,updated_at=now() WHERE id=%s", (Jsonb(config), loop_id))
            return {"loop": loop_id, "old": old, "new": code_identity(), "reason": reason}
