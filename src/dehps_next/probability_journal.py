"""Frozen-rule forward shadow evidence, independent of formal mail selections."""

import json

import numpy as np
from psycopg.types.json import Jsonb

from .domain import digest
from .errors import DomainError
from .multiscale import METHODS, VERSION, initial_specs
from .release import numeric_identity


def compatible(rule, settings):
    contract = rule["contract"]
    if digest(contract) != rule["sha256"]:
        raise DomainError("PROBABILITY_RULE_CORRUPT", "Frozen algorithm checksum differs")
    return (contract["numeric"] == numeric_identity()
            and contract.get("numeric_threads") == settings.training_threads
            and contract.get("origin_processes") == settings.origin_processes)


def research_status(db):
    rules = db.rows("""SELECT r.id,r.contract,r.created_at,count(s.issue) AS settled,
        count(f.issue) AS sealed,coalesce(sum((s.payload->>'blue_hit')::int),0) AS blue_hits,
        count(*) FILTER(WHERE (s.payload->>'red_max_matches')::int>=5) AS red5_periods,
        avg((s.payload->>'red_brier')::float) AS red_brier,
        avg((s.payload->>'blue_log_loss')::float) AS blue_log_loss FROM probability_rules r
        LEFT JOIN probability_forecasts f ON f.rule_id=r.id
        LEFT JOIN probability_settlements s ON s.rule_id=f.rule_id AND s.issue=f.issue
        GROUP BY r.id ORDER BY r.created_at DESC LIMIT 3""")
    return {"methods": list(METHODS), "feature_windows": [10, 30, 100], "initial_recipes": 36,
            "rules": rules, "scope": "RESEARCH_SHADOW_SEPARATE_FROM_FORMAL_HITS;FIRST30_DESCRIPTIVE_ONLY",
            "latest": db.rows("""SELECT node_id,spec,created_at,payload->'probability_diagnostics' AS diagnostics
                FROM research_memory_events WHERE kind='EVALUATION' AND spec->>'method'=ANY(%s)
                ORDER BY seq DESC LIMIT 1""", (list(METHODS),))}


def maintain(db, artifacts):
    """Select only after the frozen36 grid, then schedule fixed-rule future refits."""
    from .data import DataService
    from .forecast import assess
    from .research import Research
    from .scores import decode
    from .training_window import status

    with db.pool.connection() as c, c.transaction():
        if not c.execute("SELECT pg_try_advisory_xact_lock(740148) AS locked").fetchone()["locked"]:
            return {"state": "BUSY"}
        if status(c)["paused"]:
            return {"state": "PAUSED_DRAW_WINDOW"}
        rules = c.execute("SELECT * FROM probability_rules ORDER BY created_at DESC LIMIT 1").fetchall()
        dataset = DataService(db, artifacts).research_snapshot(c)
        if not rules:
            completed = c.execute("""SELECT spec_digest FROM research_recipe_memory
                WHERE dataset_id=%s AND numeric_digest=%s AND verdict IS NOT NULL""",
                (dataset["id"], numeric_identity())).fetchall()
            if not {digest(s) for s in initial_specs()} <= {r["spec_digest"] for r in completed}:
                return {"state": "WAITING_FROZEN36_COMPLETION"}
            candidates = c.execute("""SELECT n.*,r.protocol,r.dataset_id FROM research_nodes n
                JOIN research_campaigns r ON r.id=n.campaign_id WHERE r.program_id='autonomous-v2'
                AND r.dataset_id=%s AND r.config->>'numeric_digest'=%s
                AND n.spec->>'method'=ANY(%s) AND n.status='ACCEPT_IMPROVEMENT'
                ORDER BY n.completed_at DESC LIMIT 64""", (dataset["id"], numeric_identity(), list(METHODS))).fetchall()
            selected = None
            for node in candidates:
                snapshot = json.loads(artifacts.read(dataset["artifact"]))
                scores = decode(artifacts.read(node["evaluation"]["scores"]))["rows"]
                if assess(scores, node["protocol"], node["decision"], snapshot)["eligible"]:
                    selected = node
                    break
            if not selected:
                return {"state": "NO_QUALIFIED_DYNAMIC_RULE;CONTINUE_RESEARCH"}
            contract = {"feature_version": VERSION, "spec": selected["spec"], "numeric": numeric_identity(),
                        "numeric_threads": db.settings.training_threads, "origin_processes": db.settings.origin_processes,
                        "selected_node": selected["id"], "dataset": dataset["artifact"],
                        "model": selected["evaluation"]["publication_anchor"], "scores": selected["evaluation"]["scores"],
                        "first_review_after_unique_draws": 30, "update_rule": "fresh_prior_fit_same_recipe_each_draw",
                        "evidence_class": "FORWARD_SHADOW",
                        "scope": "PROSPECTIVE_SHADOW;NOT_FORMAL_RECOMMENDATION_OR50_PERCENT_PROOF"}
            identity = "multiscale-forward-" + digest(contract)[:24]
            c.execute("INSERT INTO probability_rules(id,program_id,contract,sha256) VALUES(%s,'autonomous-v2',%s,%s)",
                      (identity, Jsonb(contract), digest(contract)))
            rules = [{"id": identity, "contract": contract, "sha256": digest(contract)}]
        rule = rules[0]
        if not compatible(rule, db.settings):
            return {"state": "FROZEN_RULE_REQUIRES_ORIGINAL_RUNTIME"}
        name = rule["id"] + "-" + dataset["through_issue"]
        Research(db, artifacts).create(name, planner="rules", root_spec=rule["contract"]["spec"],
            study_source={"id": rule["id"], "purpose": "PROSPECTIVE_FIXED_RULE"}, connection=c)
        return {"state": "FROZEN_RULE_REFIT_SCHEDULED", "campaign": name}


def tick(db, artifacts, target, clock):
    """Seal only at the existing draw-day gate; settle only verified official labels."""
    from .calendar import ZONE
    from .data import DataService
    from .research_compute import predict_anchor

    with db.pool.connection() as c, c.transaction():
        c.execute("SELECT pg_advisory_xact_lock(740148)")
        pending = c.execute("""SELECT f.*,d.red,d.blue,p.source_id,p.first_verified_at FROM probability_forecasts f
            JOIN effective_draws d ON d.issue=f.issue JOIN official_publications p ON p.issue=f.issue
            LEFT JOIN probability_settlements s ON s.rule_id=f.rule_id AND s.issue=f.issue
            WHERE s.issue IS NULL AND d.draw_at<=%s AND p.first_verified_at<=%s
            AND f.created_at<d.draw_at""", (clock, clock)).fetchall()
        for f in pending:
            red = np.array(f["payload"]["red_probabilities"])
            blue = np.array(f["payload"]["blue_probabilities"])
            y = np.zeros(33)
            y[np.array(f["red"])-1] = 1
            metrics = {"red_brier": float(np.mean((red-y)**2)), "blue_log_loss": float(-np.log(blue[f["blue"]-1])),
                       "blue_hit": int(f["payload"]["blue_top1"] == f["blue"]),
                       "red_max_matches": max(len(set(t)&set(f["red"])) for t in f["payload"]["red_top100"]),
                       "source_id": f["source_id"], "official_verified_at": f["first_verified_at"].isoformat(),
                       "evidence_class": f["payload"].get("evidence_class", "FORWARD_SHADOW"),
                       "scope": "FROZEN_RULE_FORWARD_SHADOW;SEPARATE_FROM_FORMAL_HITS"}
            c.execute("INSERT INTO probability_settlements(rule_id,issue,payload) VALUES(%s,%s,%s)",
                      (f["rule_id"], f["issue"], Jsonb(metrics)))
        local = clock.astimezone(ZONE)
        if not (local.date() == target["day"] and target["prepare_time"] <= local < target["deadline_time"]):
            return {"settled": len(pending), "seal": "WAITING_17_00"}
        if c.execute("SELECT 1 FROM jobs WHERE state='RUNNING' AND kind IN ('TRAIN','RESEARCH_EVALUATE','RESEARCH_PLAN') AND lease_until>now()").fetchone():
            return {"settled": len(pending), "seal": "WAITING_CHECKPOINT"}
        rules = c.execute("SELECT * FROM probability_rules ORDER BY created_at DESC LIMIT 1").fetchall()
        if not rules:
            return {"settled": len(pending), "seal": "NO_FROZEN_QUALIFIED_RULE"}
        rule = rules[0]
        if c.execute("SELECT 1 FROM probability_forecasts WHERE rule_id=%s AND issue=%s", (rule["id"], target["issue"])).fetchone():
            return {"settled": len(pending), "seal": "ALREADY_SEALED"}
        if not compatible(rule, db.settings):
            return {"settled": len(pending), "seal": "FROZEN_RULE_REQUIRES_ORIGINAL_RUNTIME"}
        dataset = DataService(db, artifacts).research_snapshot(c)
        name = rule["id"] + "-" + dataset["through_issue"]
        node = c.execute("SELECT * FROM research_nodes WHERE campaign_id=%s AND evaluation IS NOT NULL", (name,)).fetchone()
        if not node:
            return {"settled": len(pending), "seal": "MISSING_FIXED_RULE_REFIT"}
        data = json.loads(artifacts.read(dataset["artifact"]))
        from .domain import timestamp

        if any(timestamp(r["draw_at"]) >= target["draw_time"] or
               timestamp(r["available_at"]) > target["prepare_time"] or
               timestamp(r["observed_at"]) > target["prepare_time"] for r in data["rows"]):
            raise DomainError("PROBABILITY_PRIOR_BOUNDARY", "Forward shadow snapshot exceeds the seal cutoff")
        prediction = predict_anchor(artifacts.read(node["evaluation"]["publication_anchor"]), data["rows"])
        payload = {**prediction, "rule": rule["id"], "sealed_at": clock.isoformat(),
                   "evidence_class": rule["contract"].get("evidence_class", "FORWARD_SHADOW"),
                   "dataset": dataset["artifact"], "model": node["evaluation"]["publication_anchor"],
                   "scope": "FROZEN_RULE_FORWARD_SHADOW;NOT_FORMAL_RECOMMENDATION"}
        c.execute("INSERT INTO probability_forecasts(rule_id,issue,payload) VALUES(%s,%s,%s)",
                  (rule["id"], target["issue"], Jsonb(payload)))
        return {"settled": len(pending), "seal": "SEALED_SHADOW"}
