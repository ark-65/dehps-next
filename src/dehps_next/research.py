"""Single authoritative branch controller, dispatched through the existing leased queue."""

import json
from contextlib import nullcontext

from psycopg.types.json import Jsonb

from .data import DataService
from .domain import digest
from .errors import DomainError
from .release import code_identity, numeric_identity
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

    def create(
        self,
        name,
        *,
        planner="rules",
        max_nodes=3,
        recent=100,
        historical=200,
        root_spec=None,
        topic=None,
        program_id=None,
        launch_identity=None,
        connection=None,
        recovery_source=None,
        recovery_dataset=None,
        recovery_protocol=None,
    ):
        if planner not in ("rules", "local") or not 2 <= max_nodes <= 8 or not name or len(name) > 80:
            raise DomainError("RESEARCH_POLICY", "Invalid campaign, planner or node budget")
        root_spec = root_spec or ROOT_SPEC
        validate_spec(root_spec)
        if self.db.settings.research_validation == "recent-windows-v4" and topic:
            topic = {
                **topic,
                "question": "Improve red5+ Top100 and blueTop1 hit rates on chronological100/50/10 replay without future labels",
            }
        config = {
            "planner": planner,
            "max_nodes": max_nodes,
            "root_spec": root_spec,
            "topic": topic,
            "numeric_threads": self.db.settings.training_threads,
            "origin_processes": self.db.settings.origin_processes,
            "proposal_policy": self.db.settings.research_agent,
            "pipeline_depth": self.db.settings.research_pipeline_depth,
            "validation_policy": self.db.settings.research_validation,
            "numeric_cpu_pool": self.db.settings.cpu_pool,
            "inference_threads": self.db.settings.inference_threads,
            "inference_backend": self.db.settings.inference_backend,
            "inference_busy_threads": self.db.settings.inference_busy_threads,
            "code_digest": code_identity(),
            "numeric_digest": numeric_identity(),
            "node_seconds": 600,
            "recent": recent,
            "historical": 0 if self.db.settings.research_validation == "recent-windows-v4" else historical,
            "inference_policy": "LOCAL_TOKEN_OBSERVATION_ONLY",
            "purpose": "DEVELOPMENT_RESEARCH_NOT_FORMAL_PREDICTION",
        }
        if recovery_source:
            config["recovery_source"] = recovery_source
        with nullcontext(connection) if connection else self.db.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(740134)")
            previous = c.execute("SELECT * FROM research_campaigns WHERE id=%s", (name,)).fetchone()
            if previous:
                if previous["config"] != config:
                    raise DomainError("CAMPAIGN_CONFLICT", "Existing research config is frozen")
                return previous
            if recovery_dataset and recovery_source and recovery_protocol:
                dataset = c.execute("SELECT * FROM datasets WHERE id=%s", (recovery_dataset,)).fetchone()
                if not dataset:
                    raise DomainError("RECOVERY_DATA_MISSING", "Original recovery snapshot is required")
                protocol = recovery_protocol
            elif recovery_dataset or recovery_protocol:
                raise DomainError(
                    "RECOVERY_CONTRACT_REQUIRED", "Recovery must name its source and original protocol"
                )
            elif self.db.settings.research_validation == "recent-windows-v4":
                from .research_hits import make_protocol as make_recent_protocol

                dataset = DataService(self.db, self.artifacts).research_snapshot(c)
                protocol = make_recent_protocol(dataset["sample_count"])
            else:
                dataset = DataService(self.db, self.artifacts).research_snapshot(c)
                protocol = make_protocol(dataset["sample_count"], recent, historical)
            c.execute(
                """INSERT INTO research_campaigns(id,config,dataset_id,protocol)
                VALUES(%s,%s,%s,%s)""",
                (name, Jsonb(config), dataset["id"], Jsonb(protocol)),
            )
            c.execute(
                "UPDATE research_campaigns SET program_id=%s,topic=%s,identity=%s WHERE id=%s",
                (program_id, topic["name"] if topic else None, launch_identity, name),
            )
            self._node(
                c,
                name,
                "1",
                None,
                root_spec,
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
        from .research_memory import remember

        campaign_row = c.execute(
            "SELECT dataset_id FROM research_campaigns WHERE id=%s", (campaign,)
        ).fetchone()
        remember(c, campaign_row["dataset_id"], numeric_identity(), spec)
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
                "SELECT * FROM research_campaigns WHERE status NOT IN ('BATCH_COMPLETE','BUDGET_EXHAUSTED','COMPLETE','SUPERSEDED','SEARCH_EXHAUSTED') AND status NOT LIKE 'BLOCKED_%%'"
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
        from .research_hits import VERSION as HIT_VERSION

        hit_mode = node["protocol"]["version"] == HIT_VERSION
        if (
            node["parent_id"]
            and node["config"].get("proposal_policy") == "candidates-v2"
            and node["config"]["planner"] == "local"
        ):
            from .research_proposals import skip_stale_node

            if skip_stale_node(self, job, node):
                return
        snapshot = json.loads(self.artifacts.read(node["dataset_artifact"]))
        from .scores import decode, encode

        saved = decode(self.artifacts.read(job["checkpoint"])) if job["checkpoint"] else None
        cache_key = digest(
            [
                node["spec"],
                node["protocol"]["digest"],
                node["dataset_artifact"]["sha256"],
                node["config"].get("numeric_digest", node["config"]["code_digest"]),
                node["config"].get("numeric_threads", 2),
            ]
        )
        cached = self.db.rows("SELECT artifact FROM research_score_cache WHERE id=%s", (cache_key,))
        verified_reuse = False
        if saved is None and not cached:
            protocol_match = (
                "(r.protocol->>'seed')::int=%s AND r.protocol->>'version' IN ('recent100-tail10-random-v2','recent100-tail50-tail10-hits-v4')"
                if hit_mode
                else "r.protocol->>'digest'=%s"
            )
            cached = self.db.rows(
                """SELECT n.evaluation->'scores' AS artifact FROM research_nodes n
                JOIN research_campaigns r ON r.id=n.campaign_id JOIN datasets ds ON ds.id=r.dataset_id
                LEFT JOIN numeric_releases nr ON nr.release_digest=r.config->>'code_digest'
                JOIN artifact_catalog ac ON ac.path=n.evaluation->'scores'->>'path' AND ac.state!='DELETED'
                WHERE coalesce(r.config->>'numeric_digest',nr.numeric_digest)=%s AND n.spec=%s
                AND """
                + protocol_match
                + """ AND ds.artifact->>'sha256'=%s
                AND (r.config->>'numeric_threads')::int=%s AND n.evaluation IS NOT NULL
                ORDER BY n.completed_at DESC LIMIT 1""",
                (
                    numeric_identity(),
                    Jsonb(node["spec"]),
                    node["protocol"]["seed"] if hit_mode else node["protocol"]["digest"],
                    node["dataset_artifact"]["sha256"],
                    node["config"].get("numeric_threads", 2),
                ),
            )
            verified_reuse = bool(cached)
        if saved is None and cached:
            saved = decode(self.artifacts.read(cached[0]["artifact"]))
            if hit_mode:
                wanted = set(node["protocol"]["origins"])
                saved["rows"] = sorted(
                    (r for r in saved["rows"] if r["origin"] in wanted), key=lambda r: r["origin"]
                )
                if [r["origin"] for r in saved["rows"]] != node["protocol"]["origins"]:
                    saved, cached, verified_reuse = None, [], False
            if saved is not None:
                saved["identity"] = digest([node["spec"], node["protocol"]["digest"], snapshot["cutoff"]])
        parent = (
            self.db.rows("SELECT * FROM research_nodes WHERE id=%s", (node["parent_id"],))
            if node["parent_id"]
            else []
        )
        initial = self.artifacts.read(parent[0]["anchor"]) if parent else None

        committed_prefix = [len(saved["rows"]) if saved else 0]

        def checkpoint(payload):
            # Flushing a completed prefix is permitted during pause; fencing is still mandatory.
            self.db.heartbeat(job)
            ref = self.artifacts.write(
                encode(payload["rows"], payload["identity"]),
                category="checkpoints",
            )
            self.artifacts.read(ref)
            self.db.checkpoint(job, ref, progress=(node, max(0, len(payload["rows"]) - committed_prefix[0])))
            committed_prefix[0] = len(payload["rows"])

        # Root prepares the reserve once; children spend the extra fits only after uncertainty.
        include_reserve = not parent or (
            saved is not None and len(saved["rows"]) > len(node["protocol"]["origins"])
        )
        scores, anchor_bytes, publication_bytes, execution = compute_node(
            snapshot,
            node["spec"],
            node["protocol"],
            pulse,
            checkpoint,
            saved=saved,
            initial=initial,
            seconds=node["config"]["node_seconds"],
            include_reserve=include_reserve,
            processes=node["config"].get("origin_processes", 1),
            threads=node["config"].get("numeric_threads", 2),
        )
        parent_scores = (
            decode(self.artifacts.read(parent[0]["evaluation"]["scores"]))["rows"] if parent else None
        )
        business = None
        if hit_mode:
            from .research_hits import measure, public
            from .research_hits import review as review_hits

            business = measure(scores, snapshot, node["protocol"])
            verdict = (
                review_hits(measure(parent_scores, snapshot, node["protocol"]), business, node["protocol"])
                if parent
                else {"verdict": "ACCEPT_BASELINE", "protocol_digest": node["protocol"]["digest"]}
            )
        else:
            verdict = (
                review(parent_scores, scores, node["protocol"])
                if parent
                else {"verdict": "ACCEPT_BASELINE", "protocol_digest": node["protocol"]["digest"]}
            )
        extra = bool(
            parent
            and node["protocol"]["reserve"]
            and verdict["verdict"] != "PRUNE_REGRESSION"
            and not include_reserve
            and len(parent_scores) == len(node["protocol"]["origins"]) + len(node["protocol"]["reserve"])
        )
        if extra:
            prior_execution = execution
            scores, anchor_bytes, publication_bytes, execution = compute_node(
                snapshot,
                node["spec"],
                node["protocol"],
                pulse,
                checkpoint,
                saved={
                    "identity": digest([node["spec"], node["protocol"]["digest"], snapshot["cutoff"]]),
                    "rows": scores,
                },
                initial=initial,
                seconds=node["config"]["node_seconds"],
                include_reserve=True,
                processes=node["config"].get("origin_processes", 1),
                threads=node["config"].get("numeric_threads", 2),
            )
            execution["resumed_origins"] = prior_execution["resumed_origins"]
            execution["origin_fits_executed_this_attempt"] += prior_execution[
                "origin_fits_executed_this_attempt"
            ]
            execution["gradient_steps_executed_this_attempt"] += prior_execution[
                "gradient_steps_executed_this_attempt"
            ]
            execution["seconds_this_attempt"] += prior_execution["seconds_this_attempt"]
            verdict = review(parent_scores, scores, node["protocol"])
        execution["finite_reserve_extension"] = extra
        execution["reserve_fits_available"] = sum(r["origin"] in node["protocol"]["reserve"] for r in scores)
        execution["history_source"] = (
            "TASK_CHECKPOINT"
            if job["checkpoint"]
            else "VERIFIED_NUMERIC_EQUIVALENT_SCORES"
            if verified_reuse
            else "SHARED_SCORE_CACHE"
            if cached
            else "FRESH_PRIOR_FITS"
        )
        score_ref = self.artifacts.write(encode(scores), category="research/scores")
        anchor_ref = self.artifacts.write(anchor_bytes, category="research/anchors")
        publication_ref = self.artifacts.write(publication_bytes, category="research/anchors")
        evaluation = {
            "scores": score_ref,
            "publication_anchor": publication_ref,
            "publication_training": "fresh_prior_fit_matching_every_historical_origin",
            "summary": summary(scores, node["protocol"]["origins"]),
            "recent100": summary(scores, node["protocol"]["recent"]),
            "recent10": summary(scores, node["protocol"].get("recent10", node["protocol"]["recent"][-10:])),
            "random_historical": summary(scores, node["protocol"]["random_historical"])
            if node["protocol"]["random_historical"]
            else None,
            "protocol_digest": node["protocol"]["digest"],
            "execution": execution,
            "evidence": node["protocol"]["evidence"],
        }
        if hit_mode:
            evaluation["recent50"] = summary(scores, node["protocol"]["recent50"])
            evaluation["business"] = public(business)
            execution["score_reuse_scope"] = (
                "exact100_origins_same_data_seed_math_threads;hit_metrics_recomputed"
                if cached
                else "new_prior_fits"
            )
        pulse()
        with self.db.pool.connection() as c, c.transaction():
            self.db.fence(c, job)
            c.execute("SELECT id FROM research_campaigns WHERE id=%s FOR UPDATE", (node["campaign_id"],))
            c.execute(
                "INSERT INTO research_score_cache(id,artifact) VALUES(%s,%s) ON CONFLICT(id) DO UPDATE SET artifact=excluded.artifact,created_at=now()",
                (cache_key, Jsonb(score_ref)),
            )
            c.execute(
                """UPDATE research_nodes SET evaluation=%s,anchor=%s,decision=%s,status=%s,
                completed_at=now() WHERE id=%s""",
                (Jsonb(evaluation), Jsonb(anchor_ref), Jsonb(verdict), verdict["verdict"], node["id"]),
            )
            from .research_memory import remember

            remember(
                c,
                node["dataset_id"],
                numeric_identity(),
                node["spec"],
                verdict["verdict"],
                evaluation["summary"],
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
            from .research_memory import archive_node

            archive_node(
                c,
                node["id"],
                periods=business["periods"] if business else None,
                origin_provenance=[
                    {
                        "origin": row["origin"],
                        "issue": row["issue"],
                        "training_through": row["training_through"],
                        "prior_available_at": snapshot["rows"][row["origin"] - 1]["available_at"],
                        "target_draw_at": snapshot["rows"][row["origin"]]["draw_at"],
                        "target_source_id": snapshot["rows"][row["origin"]].get("source_id"),
                        "weight_digest": row["weight_digest"],
                        "mathematical_digest": row.get("mathematical_digest"),
                        "probability_digest": digest([row["red_probabilities"], row["blue_probabilities"]]),
                    }
                    for row in scores
                ],
            )
            self.db.complete(c, job)
            c.execute("UPDATE jobs SET checkpoint=NULL WHERE id=%s", (job["id"],))
        self.artifacts.cleanup_checkpoints(job["id"])

    def plan(self, job, context, pulse):
        if context["config"].get("recovery_source"):
            with self.db.pool.connection() as c, c.transaction():
                self.db.fence(c, job)
                c.execute(
                    "UPDATE research_campaigns SET status='COMPLETE',updated_at=now() WHERE id=%s",
                    (context["campaign_id"],),
                )
                self.decision(
                    c,
                    context["campaign_id"],
                    context["id"],
                    "RECOVERY_COMPLETE",
                    {
                        "source": context["config"]["recovery_source"],
                        "evidence": "RECOVERED_EVALUATION_NOT_CHAMPION_PROMOTION",
                    },
                )
                self.db.complete(c, job)
            return
        if (
            context["config"].get("proposal_policy") == "candidates-v2"
            and context["config"]["planner"] == "local"
        ):
            from .research_proposals import plan_batch

            return plan_batch(self, job, context, pulse)
        campaign = self.db.rows("SELECT * FROM research_campaigns WHERE id=%s", (context["campaign_id"],))[0]
        nodes = self.db.rows(
            "SELECT * FROM research_nodes WHERE campaign_id=%s ORDER BY created_at", (campaign["id"],)
        )
        if len(nodes) >= campaign["config"]["max_nodes"]:
            with self.db.pool.connection() as c, c.transaction():
                self.db.fence(c, job)
                c.execute(
                    "UPDATE research_campaigns SET status='BATCH_COMPLETE',updated_at=now() WHERE id=%s",
                    (campaign["id"],),
                )
                self.decision(c, campaign["id"], context["id"], "BATCH_COMPLETE", {"nodes": len(nodes)})
                self.db.complete(c, job)
            return
        selected = next(n for n in nodes if n["id"] == campaign["selected_node"])
        siblings = [n for n in nodes if n["parent_id"] == selected["id"]]
        spec = dict(selected["spec"])
        if campaign["config"]["planner"] == "local":
            from .research_agent import propose, use_local_model
            from .research_search import propose_adaptive

            try:
                proposal = (propose if use_local_model(self.db, campaign, nodes) else propose_adaptive)(
                    campaign, nodes, pulse, self.db, self.artifacts, job
                )
            except DomainError as exc:
                if exc.code != "SEARCH_SPACE_EXHAUSTED":
                    raise
                try:
                    proposal = propose_adaptive(campaign, nodes, pulse, self.db, self.artifacts, job)
                    proposal["local_review"] = (
                        "Local proposals repeated tried recipes; choose a novel executable direction"
                    )
                except DomainError as exhausted:
                    if exhausted.code != "SEARCH_SPACE_EXHAUSTED":
                        raise
                    self.exhaust(campaign, context, job)
                    return
            spec.update(proposal["spec"])
            hypothesis = proposal
        elif not siblings:
            spec["learning_rate"] = 0.05
            hypothesis = {
                "source": "BOUNDED_RULE_PLANNER",
                "hypothesis": "A more aggressive learning rate may improve adaptation",
                "falsification": "Paired recent and random historical blue loss confirms regression",
            }
        elif len(siblings) == 1:
            spec["learning_rate"], spec["weight_decay"] = 0.0005, 0.01
            hypothesis = {
                "source": "BOUNDED_RULE_PLANNER",
                "hypothesis": "Lower learning rate and shrinkage may reduce overfit",
                "falsification": "Same frozen validation list shows no reliable improvement",
            }
        else:
            from .research_search import propose_adaptive

            hypothesis = propose_adaptive(campaign, nodes, pulse, self.db, self.artifacts, job)
            spec.update(hypothesis["spec"])
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

    def exhaust(self, campaign, context, job):
        with self.db.pool.connection() as c, c.transaction():
            self.db.fence(c, job)
            c.execute(
                "UPDATE research_campaigns SET status='SEARCH_EXHAUSTED',updated_at=now() WHERE id=%s",
                (campaign["id"],),
            )
            self.decision(
                c,
                campaign["id"],
                context["id"],
                "SEARCH_SPACE_EXHAUSTED",
                {"reason": "Local hypotheses and registered adaptive curricula contain no novel recipe"},
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
