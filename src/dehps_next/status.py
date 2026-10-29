import random

from .domain import digest
from .release import code_identity


def get_status(db, artifacts):
    loops = db.rows("SELECT id,mode,state,config,updated_at FROM loops ORDER BY created_at")
    for loop in loops:
        evidence = db.rows(
            """SELECT e.issue,e.mode,e.metrics FROM evaluations e
            JOIN cycles cy ON e.cycle_id=cy.id WHERE cy.loop_id=%s ORDER BY cy.draw_at""",
            (loop["id"],),
        )
        recent = evidence[-10:]
        historical = random.Random(1729).sample(evidence, min(10, len(evidence)))
        loop["evaluated_issues"] = len(evidence)
        loop["blue_top1_hits"] = sum(e["metrics"]["blue_top1_hit"] for e in evidence)
        loop["blue_top1_rate"] = loop["blue_top1_hits"] / len(evidence) if evidence else None
        loop["blue_50_percent_evidence"] = "NOT_ESTABLISHED"
        loop["evaluation_protocol"] = {
            "type": "descriptive_prequential_audit_not_independent_research_validation",
            "recent_issues": [e["issue"] for e in recent],
            "random_historical_issues": [e["issue"] for e in historical],
            "seed": 1729,
            "overlap_not_added_to_sample_count": True,
            "list_digest": digest([e["issue"] for e in historical]),
            "full_branch_comparison_and_protected_holdout": "P2_PENDING",
        }
    return {
        "code_digest": code_identity(),
        "loops": loops,
        "jobs": db.rows("SELECT state,kind,count(*) AS count FROM jobs GROUP BY state,kind"),
        "workers": db.rows("SELECT * FROM worker_status ORDER BY id"),
        "draws": db.rows("SELECT count(*) AS count,max(issue) AS latest_issue FROM draws")[0],
        "models": db.rows("SELECT count(*) AS count FROM models")[0]["count"],
        "new_label_consumptions": db.rows("SELECT count(*) AS count FROM consumptions WHERE newly_consumed")[
            0
        ]["count"],
        "owned_artifact_bytes": artifacts.usage(),
        "artifact_quota_bytes": db.settings.quota_bytes,
        "database_bytes": db.rows("SELECT pg_database_size(current_database()) AS bytes")[0]["bytes"],
        "storage_scope": "P1 artifact bound only; whole-host envelope and TTL GC are P3 pending",
        "research_campaigns": db.rows(
            "SELECT id,status,selected_node,updated_at FROM research_campaigns ORDER BY created_at"
        ),
        "full_autonomous_research": "LOCAL_AGENT_CONFIGURATION_REQUIRED",
        "legacy_access": "NONE",
    }
