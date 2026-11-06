"""Recompute bounded prior trials under the current numeric contract; never relabel old outcomes."""

import json
from collections import Counter


def current_feedback(db, artifacts, effect, campaign, parent):
    from psycopg.types.json import Jsonb

    from dehps_next.domain import digest
    from dehps_next.release import numeric_identity
    from dehps_next.research import Research
    from dehps_next.research_review import counts

    source = "feedback-paired-12-v2"
    study = "feedback-current-numeric-20261106-v1"
    candidates = db.rows("SELECT spec_digest,payload FROM research_review_evaluations WHERE study_id=%s "
                         "ORDER BY spec_digest LIMIT 12", (source,))
    assert len(candidates) == 12 and campaign["config"]["numeric_threads"] == 1
    source_header = db.rows("SELECT protocol,sha256 FROM research_review_studies WHERE id=%s", (source,))[0]
    assert source_header["protocol"]["source_dataset"] == campaign["dataset_id"]
    assert source_header["protocol"]["validation"] == campaign["protocol"]
    assert source_header["protocol"]["parent_spec"] == parent["spec"]
    assert source_header["protocol"]["parent_business"] == parent["evaluation"]["business"]
    plan = {
        "kind": "CURRENT_NUMERIC_PRIOR_FEEDBACK_V1", "source_study": source,
        "source_study_sha256": source_header["sha256"],
        "selection": "FIRST12_SPEC_DIGEST_ORDER;FIXED_BEFORE_NEW_FITS;NO_OUTCOME_FILTER",
        "specs": [r["payload"]["spec"] for r in candidates],
        "dataset": campaign["dataset_id"], "validation": campaign["protocol"],
        "numeric": numeric_identity(), "threads": 1, "origin_processes": 8,
        "parent_business": parent["evaluation"]["business"],
        "scope": "CURRENT_NUMERIC_EVALUATIONS;AUDITED_REUSE_SEPARATE;OLD_SPECS_ONLY;SAME100_LABELS_NOT_FORWARD",
    }
    with db.pool.connection() as connection, connection.transaction():
        connection.execute("INSERT INTO research_review_studies(id,protocol,sha256) VALUES(%s,%s,%s) "
                           "ON CONFLICT DO NOTHING", (study, Jsonb(plan), digest(plan)))
        assert connection.execute("SELECT sha256 FROM research_review_studies WHERE id=%s", (study,)).fetchone()[
            "sha256"
        ] == digest(plan)
    dataset = db.rows("SELECT artifact FROM datasets WHERE id=%s", (campaign["dataset_id"],))[0]
    snapshot = json.loads(artifacts.read(dataset["artifact"]))
    parent_metrics = effect.measure(effect.decode(artifacts.read(parent["evaluation"]["scores"]))["rows"],
                                    snapshot, campaign["protocol"])
    assert {k: v for k, v in parent_metrics.items() if k != "periods"} == plan["parent_business"]
    for record in candidates:
        identity = record["spec_digest"]
        assert digest(record["payload"]["spec"]) == identity
        if db.rows("SELECT 1 FROM research_review_evaluations WHERE study_id=%s AND spec_digest=%s",
                   (study, identity)):
            continue
        name = study + "-" + identity[:10]
        Research(db, artifacts).create(
            name, root_spec=record["payload"]["spec"], max_nodes=2,
            recovery_source={"purpose": "CURRENT_NUMERIC_FEEDBACK_REFRESH", "source_study": source},
            recovery_dataset=campaign["dataset_id"], recovery_protocol=campaign["protocol"],
            study_source={"id": study},
        )
        node = effect.compute(db, artifacts, name)
        assert node["evaluation"]["execution"]["all_origin_parameters_updated"]
        child_metrics = effect.measure(effect.decode(artifacts.read(node["evaluation"]["scores"]))["rows"],
                                       snapshot, campaign["protocol"])
        assert {k: v for k, v in child_metrics.items() if k != "periods"} == node["evaluation"]["business"]
        decision = effect.review(parent_metrics, child_metrics, campaign["protocol"])
        payload = {
            "spec": node["spec"], "business": node["evaluation"]["business"], "decision": decision,
            "execution": node["evaluation"]["execution"], "numeric": plan["numeric"],
            "scores": node["evaluation"]["scores"], "model": node["evaluation"]["publication_anchor"],
            "parent_business": plan["parent_business"], "dataset": plan["dataset"],
        }
        with db.pool.connection() as connection:
            connection.execute("INSERT INTO research_review_evaluations(study_id,spec_digest,node_id,payload) "
                               "VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING", (study, identity, node["id"], Jsonb(payload)))
        print(f"current_numeric_feedback_complete {identity}", flush=True)
    rows = db.rows("SELECT * FROM research_review_evaluations WHERE study_id=%s ORDER BY spec_digest", (study,))
    assert len(rows) == 12
    families = []
    methods = sorted({r["payload"]["spec"]["method"] for r in rows})
    eligible = [r for r in rows if r["payload"]["decision"]["verdict"] in ("INCONCLUSIVE", "PRUNE_REGRESSION")]
    chosen = []
    for method in methods:
        group = [r for r in rows if r["payload"]["spec"]["method"] == method]
        verdicts = Counter(r["payload"]["decision"]["verdict"] for r in group)
        def risk(key, family_rows=group):
            return sum(any(v[key] < 0 for v in r["payload"]["decision"]["business"]["paired_windows"].values())
                       for r in family_rows)
        families.append({"method": method, "n": len(group), "red_risk": risk("red5_rate"),
                         "blue_risk": risk("blue_rate"), "improved": verdicts["ACCEPT_IMPROVEMENT"]})
        bad = [r for r in eligible if r["payload"]["spec"]["method"] == method]
        if bad:
            chosen.append(bad[0])
    for row in eligible:
        if len(chosen) >= 4:
            break
        if row not in chosen:
            chosen.append(row)
    assert chosen, "Require actual current-numeric failure/uncertainty evidence"
    evidence = [{"key": f"f{i}", "node": r["node_id"], "spec": r["payload"]["spec"],
                 "hits": counts(r["payload"]["business"]), "verdict": r["payload"]["decision"]["verdict"],
                 "paired_windows": r["payload"]["decision"]["business"]["paired_windows"]}
                for i, r in enumerate(chosen[:4])]
    return {"evidence": evidence, "families": families, "trials": len(rows),
            "source": {"study": study, "sha256": digest(plan), "numeric": plan["numeric"],
                       "scope": "CURRENT_NUMERIC_ROOT_TRIALS_WITH_EXPLICIT_PAIRED_REVIEW;NOT_PRODUCTION_CHILD_EVENTS"}}
