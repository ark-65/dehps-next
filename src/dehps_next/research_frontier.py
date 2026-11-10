"""Versioned proposal space around the retained parent; no changes to fitters/gates."""

from psycopg.types.json import Jsonb

from .domain import digest
from .errors import DomainError
from .release import code_identity, numeric_identity

NAME = "paired-parent-frontier-v1"
TOPIC = {"name": NAME, "methods": ["ridge", "fft", "newton", "raw"],
         "question": "Can a small parent-neighbor or representation change improve paired red/blue100/50/10 without nested regressions?"}


def initial_specs(parent):
    specs = []
    for field, values in (
        ("learning_rate", [round(parent["learning_rate"] * scale, 8) for scale in (.85, .95, 1.05, 1.15)]),
        ("weight_decay", [.005, .0075, .0125, .02]),
        ("train_history", [448, 576]),
        ("epochs", [32, 48]),
    ):
        specs.extend({**parent, field: value} for value in values if value != parent[field])
    specs.extend({**parent, "method": method} for method in ("raw", "fft", "newton") if method != parent["method"])
    specs.append({**parent, "hidden": 80 if parent["hidden"] != 80 else 48})
    return specs


def proposals(db, dataset, *, minimum=6):
    """Persist small questions, inspect their outcomes, then change an axis.

    A block is an experiment allocation, never a lifetime or daily work limit.
    Unselected recipes remain carried; exact failed recipes stay excluded.
    """
    from .research_memory import untried_specs
    from .research_search import _radical_inverse
    from .research_compute import validate_spec

    numeric = numeric_identity()
    key = digest([dataset, numeric, NAME])
    with db.pool.connection() as c, c.transaction():
        c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,740143))", (key,))
        parent = c.execute("SELECT champion_spec FROM research_programs WHERE id='autonomous-v2'").fetchone()
        if not parent or not parent["champion_spec"]:
            raise DomainError("FRONTIER_PARENT_REQUIRED", "Require the retained accepted parent recipe")
        parent = parent["champion_spec"]
        previous = c.execute("""SELECT * FROM research_search_batches WHERE dataset_id=%s
            AND numeric_digest=%s AND topic=%s ORDER BY generation DESC LIMIT 1""",
            (dataset, numeric, NAME)).fetchone()
        carry, stage, cursor, generation = [], 0, 1, 1
        evidence = {"completed": 0, "improved": 0, "verdicts": {}}
        if previous:
            carry = untried_specs(db, dataset, previous["candidates"], connection=c)
            if len(carry) >= minimum:
                return carry
            generation = previous["generation"] + 1
            cursor = previous["basis"]["next_global_cursor"]
            verdicts = c.execute("""SELECT CASE WHEN EXISTS(
                    SELECT 1 FROM research_memory_events e WHERE e.dataset_id=m.dataset_id
                    AND e.numeric_digest=m.numeric_digest AND e.spec=m.spec
                    AND e.kind='EVALUATION' AND e.payload->>'verdict'='ACCEPT_IMPROVEMENT'
                ) THEN 'ACCEPT_IMPROVEMENT' ELSE m.verdict END AS outcome,count(*) AS n
                FROM research_recipe_memory m WHERE dataset_id=%s AND numeric_digest=%s AND spec_digest=ANY(%s)
                  AND verdict IS NOT NULL AND verdict!='STALE_UNTRAINED' GROUP BY outcome""",
                (dataset, numeric, [digest(s) for s in previous["candidates"]])).fetchall()
            evidence["verdicts"] = {r["outcome"]: r["n"] for r in verdicts}
            evidence["completed"] = sum(r["n"] for r in verdicts)
            evidence["improved"] = evidence["verdicts"].get("ACCEPT_IMPROVEMENT", 0)
            stage = previous["basis"]["stage"]
            if previous["basis"]["parent_digest"] != digest(parent) or evidence["improved"]:
                stage = 0
            elif evidence["completed"] >= 24:
                stage = (stage + 1) % 3
        candidates = list(carry)
        if generation == 1:
            candidates.extend(untried_specs(db, dataset, initial_specs(parent), connection=c))
        seen = {digest(s) for s in candidates}
        while len(candidates) < 32:
            offered = []
            for i in range(cursor, cursor + 128):
                u = [_radical_inverse(i, p) for p in (2, 3, 5, 7, 11, 13)]
                spec = dict(parent)
                if stage == 0:
                    # Test finer local regularization rather than resetting the
                    # entire representation to failed shared-frequency logits.
                    spec["learning_rate"] = round(min(.1, max(.00001, parent["learning_rate"] * (0.8 + .4*u[0]))), 8)
                    spec["weight_decay"] = round(min(1, max(0, parent["weight_decay"] * (.8 + .4*u[1]))), 8)
                elif stage == 1:
                    spec["window"] = max(2, min(64, parent["window"] + (-16, -8, 8, 16)[min(3, int(u[0]*4))]))
                    spec["hidden"] = max(8, min(256, parent["hidden"] + (-32, -16, 16, 32)[min(3, int(u[1]*4))]))
                    spec["train_history"] = max(64, min(1024, parent["train_history"] + int((u[2]-.5)*256)))
                else:
                    spec["method"] = TOPIC["methods"][min(3, int(u[0]*4))]
                    spec["epochs"] = max(1, min(200, parent["epochs"] + int((u[1]-.5)*32)))
                    spec["train_history"] = max(64, min(1024, parent["train_history"] + int((u[2]-.5)*256)))
                    spec["learning_rate"] = round(min(.1, max(.00001, parent["learning_rate"] * (.75+.5*u[3]))), 8)
                validate_spec(spec)
                offered.append(spec)
            cursor += 128
            for spec in untried_specs(db, dataset, offered, connection=c):
                identity = digest(spec)
                if identity not in seen:
                    candidates.append(spec); seen.add(identity)
                if len(candidates) == 32:
                    break
        basis = {"policy": "paired-gate-frontier-v1", "stage": stage,
                 "question": ("local_regularization", "history_capacity", "representation")[stage],
                 "parent_digest": digest(parent), "anchors": [parent],
                 "previous_block": evidence, "carried_untried": len(carry),
                 "neighbor_count": len(candidates), "global_count": 0,
                 "next_global_cursor": cursor,
                 "futility": "change_question_after_at_least24_completed_without_joint_improvement;never_stop_primary_training",
                 "evidence": "REGISTERED_UNTRAINED_PROPOSALS;NOT_PROGRESS_OR_FORWARD_PROOF"}
        c.execute("""INSERT INTO research_search_batches(dataset_id,numeric_digest,topic,generation,candidates,basis)
            VALUES(%s,%s,%s,%s,%s,%s)""", (dataset, numeric, NAME, generation, Jsonb(candidates), Jsonb(basis)))
        return candidates


def activate(db, program, study, reason):
    if len(reason) < 24:
        raise DomainError("DIRECTION_REVIEW_REQUIRED", "Record the measured reason for the direction change")
    with db.pool.connection() as c, c.transaction():
        c.execute("SELECT pg_advisory_xact_lock(740141)")
        p = c.execute("SELECT * FROM research_programs WHERE id=%s FOR UPDATE", (program,)).fetchone()
        if not p or p["config"]["code_digest"] != code_identity():
            raise DomainError("PROGRAM_RELEASE_CHANGED", "Adopt the reviewed controller first")
        if c.execute("""SELECT 1 FROM jobs j JOIN research_nodes n ON n.id=j.research_node_id
            JOIN research_campaigns r ON r.id=n.campaign_id WHERE r.program_id=%s
            AND j.state IN ('READY','RUNNING') LIMIT 1""", (program,)).fetchone():
            raise DomainError("ACTIVE_PROGRAM", "Finish the frozen campaign before changing direction")
        proof = c.execute("SELECT payload FROM research_review_results WHERE study_id=%s", (study,)).fetchone()
        if not proof or proof["payload"].get("numeric") != numeric_identity() or not proof["payload"].get("complete"):
            raise DomainError("DIRECTION_EVIDENCE_REQUIRED", "Require completed, current-numeric comparison evidence")
        if proof["payload"].get("dataset") != p["last_dataset"] or proof["payload"].get("parent_spec") != p["champion_spec"]:
            raise DomainError("DIRECTION_EVIDENCE_STALE", "Recheck the comparison against the current dataset and parent")
        config = {**p["config"], "topics": [TOPIC], "direction_study": study,
                  "parked_topics": p["config"]["topics"]}
        c.execute("INSERT INTO resource_policy_changes(policy,reason) VALUES(%s,%s)",
            (Jsonb({"operation": "MEASURED_RESEARCH_DIRECTION", "program": program,
                    "old_config": p["config"], "new_config": config, "study": study,
                    "promotion_and_qualification_unchanged": True}), reason))
        c.execute("UPDATE research_programs SET config=%s,current_campaign=NULL,next_due=now() WHERE id=%s",
            (Jsonb(config), program))
    return {"program": program, "direction": NAME, "study": study, "effectiveness": "NOT_ESTABLISHED"}
