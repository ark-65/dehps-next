"""Measured structural research replacing the coupled three-axis rotation."""

from psycopg.types.json import Jsonb

from .color_split import RED_SPEC, TOPIC, wrap
from .domain import digest
from .errors import DomainError
from .release import code_identity, numeric_identity


def proposals(db, dataset, minimum=6):
    from .research_memory import untried_specs
    from .research_search import extended_specs

    program = db.rows("SELECT config FROM research_programs WHERE id='autonomous-v2'")[0]
    proof = db.rows("SELECT payload FROM research_review_results WHERE study_id=%s",
                    (program["config"].get("direction_study"),))
    if not proof or proof[0]["payload"].get("numeric") != numeric_identity():
        raise DomainError("SPECIALIST_EVIDENCE_REQUIRED", "Require frozen component-composition acceptance")
    seeds = proof[0]["payload"]["blue_components"]
    controls = [{**RED_SPEC, "method": m} for m in ("ridge", "raw", "fft", "newton")]
    fresh = untried_specs(db, dataset, [wrap(s) for s in seeds + controls])
    if len(fresh) >= minimum:
        return fresh
    # Future trials change the independently fitted blue procedure. The fixed
    # red procedure is structural, never another regularization/capacity cycle.
    extended = extended_specs(db, dataset, TOPIC, minimum=minimum)
    unique = {digest(s): s for s in fresh + extended}
    return list(unique.values())


def activate(db, study, reason):
    if len(reason) < 24:
        raise DomainError("DIRECTION_REVIEW_REQUIRED", "Record the actual structural diagnosis")
    with db.pool.connection() as c, c.transaction():
        c.execute("SELECT pg_advisory_xact_lock(740141)")
        p = c.execute("SELECT * FROM research_programs WHERE id='autonomous-v2' FOR UPDATE").fetchone()
        if not p or p["config"]["code_digest"] != code_identity():
            raise DomainError("PROGRAM_RELEASE_CHANGED", "Adopt the reviewed release first")
        if p["champion_spec"] != RED_SPEC:
            raise DomainError("SPECIALIST_PARENT_CHANGED", "Revalidate the frozen red procedure against the retained parent")
        if c.execute("""SELECT 1 FROM jobs j JOIN research_nodes n ON n.id=j.research_node_id
            JOIN research_campaigns r ON r.id=n.campaign_id WHERE r.program_id='autonomous-v2'
            AND j.state IN ('READY','RUNNING') LIMIT 1""").fetchone():
            raise DomainError("ACTIVE_PROGRAM", "Finish the frozen campaign before changing its research structure")
        proof = c.execute("SELECT payload FROM research_review_results WHERE study_id=%s", (study,)).fetchone()
        if (not proof or not proof["payload"].get("complete")
                or proof["payload"].get("dataset") != p["last_dataset"]
                or proof["payload"].get("numeric") != numeric_identity()
                or not proof["payload"].get("red_output_bitwise_preserved")
                or proof["payload"].get("current_gate_passes", 0) < 1):
            raise DomainError("SPECIALIST_EVIDENCE_REQUIRED", "Require real current-gate and unchanged-red acceptance, plus recorded older-window results")
        config = {**p["config"], "topics": [TOPIC], "direction_study": study,
                  "parked_coupled_topics": p["config"]["topics"]}
        c.execute("INSERT INTO resource_policy_changes(policy,reason) VALUES(%s,%s)",
                  (Jsonb({"operation": "STRUCTURAL_COLOR_SEPARATION", "old_config": p["config"],
                          "new_config": config, "study": study, "qualification_gates_unchanged": True}), reason))
        c.execute("UPDATE research_programs SET config=%s,current_campaign=NULL,next_due=now() WHERE id='autonomous-v2'",
                  (Jsonb(config),))
    return {"topic": TOPIC["name"], "study": study, "scope": "DEVELOPMENT_RESEARCH;NOT_FORWARD_PROOF"}


def study_context(db, campaign):
    if (campaign["config"].get("topic") or {}).get("name") != TOPIC["name"]:
        return None
    p = db.rows("SELECT config FROM research_programs WHERE id='autonomous-v2'")[0]
    study = p["config"].get("direction_study")
    proof = db.rows("SELECT payload FROM research_review_results WHERE study_id=%s", (study,))[0]["payload"]
    return {"study": study, "output_rule": "fixed red v1; separately fitted blue; base losses unchanged",
            "blue_hits100_50_10_parent_then_four_experts": {
                phase: [[r["windows"][k]["blue_hits"] for k in ("recent", "recent50", "recent10")]
                        for r in rows] for phase, rows in proof["results"].items()},
            "limitation": "current discovery labels reused; older windows mixed; not stable generalization or forward proof"}


def bootstrap(controller, job, context):
    """Explicit production reproduction of reviewed evidence, never a novel Qwen choice."""
    if ((context["config"].get("topic") or {}).get("name") != TOPIC["name"]
            or context["config"]["root_spec"] != RED_SPEC):
        return False
    db = controller.db
    program = db.rows("SELECT config FROM research_programs WHERE id='autonomous-v2'")[0]
    study = program["config"]["direction_study"]
    proof = db.rows("SELECT payload FROM research_review_results WHERE study_id=%s", (study,))[0]["payload"]
    if proof["dataset"] != context["dataset_id"] or proof["numeric"] != numeric_identity():
        raise DomainError("SPECIALIST_EVIDENCE_STALE", "Re-freeze the reviewed structural comparison")
    passed = [r for r in proof["results"]["current100"][1:] if r["verdict"]["verdict"] == "ACCEPT_IMPROVEMENT"]
    selected = min(passed, key=lambda r: tuple(-r["windows"][k]["blue_hits"] for k in
                   ("recent", "recent50", "recent10")) + (digest(r["spec"]),))
    with db.pool.connection() as c, c.transaction():
        db.fence(c, job)
        campaign = c.execute("SELECT * FROM research_campaigns WHERE id=%s FOR UPDATE", (context["campaign_id"],)).fetchone()
        nodes = c.execute("SELECT * FROM research_nodes WHERE campaign_id=%s", (campaign["id"],)).fetchall()
        if len(nodes) == 1:
            basis = {"parent_id": campaign["selected_node"],
                     "parent_anchor": campaign["selected_anchor"]["sha256"],
                     "dataset_id": campaign["dataset_id"], "protocol_digest": campaign["protocol"]["digest"],
                     "code_digest": campaign["config"]["code_digest"], "numeric_digest": numeric_identity(),
                     "numeric_threads": campaign["config"]["numeric_threads"],
                     "selection_profile_id": campaign["config"].get("selection_profile_id")}
            controller._node(c, campaign["id"], "1-1", campaign["selected_node"], selected["spec"],
                             {"source": "REVIEWED_STRUCTURAL_REPRODUCTION", "study": study,
                              "pipeline_basis": basis,
                              "hypothesis": "Reproduce the accepted composition under the primary fenced Worker",
                              "falsification": "Unchanged paired100/50/10; stop reproduction on changed outcomes",
                              "novelty": "KNOWN_ACCEPTANCE_RESULT;NOT_NEW_RESEARCH_OR_QWEN_CHOICE"})
        else:
            child = next(n for n in nodes if n["parent_id"])
            if child["status"] != "ACCEPT_IMPROVEMENT":
                raise DomainError("SPECIALIST_REPRODUCTION_CHANGED", "Keep the parent; investigate the failed reproduction")
            c.execute("UPDATE research_campaigns SET status='BATCH_COMPLETE',updated_at=now() WHERE id=%s", (campaign["id"],))
            controller.decision(c, campaign["id"], child["id"], "STRUCTURAL_REPRODUCTION_COMPLETE",
                                {"study": study, "novel_research": False, "actual_original_gate_promotion": True})
        db.complete(c, job)
    return True
