"""Output-preserving calibrated baseline migration; never a fabricated hit promotion."""

from psycopg.types.json import Jsonb

from .color_split import CALIBRATED_TOPIC, RED_SPEC, blue_spec, wrap
from .domain import digest
from .errors import DomainError
from .release import code_identity, numeric_identity


def proposals(db, dataset, minimum=6):
    from .research_memory import untried_specs
    from .research_search import extended_specs

    config = db.rows("SELECT config FROM research_programs WHERE id='autonomous-v2'")[0]["config"]
    proof = db.rows("SELECT payload FROM research_review_results WHERE study_id=%s", (config["direction_study"],))[0]["payload"]
    if proof["numeric"] != numeric_identity():
        raise DomainError("CALIBRATION_EVIDENCE_STALE", "Require acceptance of the current numerical contract")
    seeds = proof["blue_components"] + [{**RED_SPEC, "method": m} for m in ("ridge", "raw", "fft", "newton")]
    fresh = untried_specs(db, dataset, [wrap(s, calibrated=True) for s in seeds])
    if len(fresh) >= minimum:
        return fresh
    extra = extended_specs(db, dataset, CALIBRATED_TOPIC, minimum=minimum)
    return list({digest(s): s for s in fresh + extra}.values())


def study_context(db, campaign):
    config = db.rows("SELECT config FROM research_programs WHERE id='autonomous-v2'")[0]["config"]
    study = config["direction_study"]
    proof = db.rows("SELECT payload FROM research_review_results WHERE study_id=%s", (study,))[0]["payload"]
    return {"study": study, "rule": "label-free known six-red mass; all redTop100 and blue outputs preserved",
            "hit_progress_from_calibration": False,
            "red_brier_before_after": {phase: [r["guard"]["windows"]["recent"]["red_brier"] for r in rows]
                                      for phase, rows in proof["results"].items()},
            "qualification_before_after": {phase: [r["guard"]["eligible"] for r in rows]
                                           for phase, rows in proof["results"].items()},
            "prior_expert_cross_window_failures": proof["prior_expert_windows"],
            "scope": "probability-coherence repair; development eligibility only; not a forward edge or new hit improvement"}


def activate(db, study, reason):
    if len(reason) < 24:
        raise DomainError("CALIBRATION_REVIEW_REQUIRED", "Record the observed failure and output-preserving release decision")
    with db.pool.connection() as c, c.transaction():
        c.execute("SELECT pg_advisory_xact_lock(740141)")
        p = c.execute("SELECT * FROM research_programs WHERE id='autonomous-v2' FOR UPDATE").fetchone()
        proof = c.execute("SELECT payload FROM research_review_results WHERE study_id=%s", (study,)).fetchone()
        if not p or p["config"]["code_digest"] != code_identity() or not proof:
            raise DomainError("CALIBRATION_RELEASE_CHANGED", "Adopt the reviewed release and actual acceptance first")
        proof = proof["payload"]
        if (not proof.get("complete") or proof["numeric"] != numeric_identity()
                or proof["dataset"] != p["last_dataset"] or proof["parent_spec"] != p["champion_spec"]
                or not proof["red_top100_preserved"] or not proof["blue_probabilities_preserved"]
                or not proof["current_guard_eligible"] or not proof["all_windows_red_brier_improved"]):
            raise DomainError("CALIBRATION_PARENT_CHANGED", "Preserve every acquired improvement; revalidate if the parent or evidence changed")
        retained = c.execute("""SELECT v.snapshot->'spec' AS spec,v.snapshot->>'dataset_id' AS dataset
            FROM retained_parent_heads h JOIN retained_parent_versions v ON v.id=h.version_id
            WHERE h.program_id='autonomous-v2'""").fetchone()
        if not retained or retained["spec"] != proof["parent_spec"] or retained["dataset"] != proof["dataset"]:
            raise DomainError("CALIBRATION_PARENT_CHANGED", "A newer accepted head must never be overwritten by a stale program pointer")
        if c.execute("""SELECT 1 FROM jobs j JOIN research_nodes n ON n.id=j.research_node_id
            JOIN research_campaigns r ON r.id=n.campaign_id WHERE r.program_id='autonomous-v2'
            AND j.state IN ('READY','RUNNING') LIMIT 1""").fetchone():
            raise DomainError("ACTIVE_PROGRAM", "Finish the frozen campaign before the baseline release migration")
        config = {**p["config"], "topics": [CALIBRATED_TOPIC], "direction_study": study,
                  "prior_specialist_topics": p["config"]["topics"]}
        new = wrap(blue_spec(p["champion_spec"]), calibrated=True)
        c.execute("INSERT INTO resource_policy_changes(policy,reason) VALUES(%s,%s)",
                  (Jsonb({"operation": "OUTPUT_PRESERVING_CARDINALITY_BASELINE_RELEASE",
                          "old_spec": p["champion_spec"], "new_spec": new, "old_config": p["config"],
                          "new_config": config, "study": study, "new_hit_promotion": False,
                          "qualification_gates_unchanged": True}), reason))
        c.execute("""UPDATE research_programs SET config=%s,champion_spec=%s,current_campaign=NULL,
                    next_due=now() WHERE id='autonomous-v2'""", (Jsonb(config), Jsonb(new)))
    return {"topic": CALIBRATED_TOPIC["name"], "baseline_spec": new,
            "new_hit_promotion": False, "scope": "REVALIDATE_OUTPUT_PRESERVING_BASELINE;NOT_FORWARD_PROOF"}
