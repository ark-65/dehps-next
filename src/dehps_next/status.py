import os
import random

from .domain import digest
from .errors import DomainError
from .release import code_identity
from .resources import Resources


def get_status(db, artifacts):
    try:
        host_capacity = Resources(db).telemetry()
    except DomainError as exc:
        host_capacity = {"complete": False, "reason": exc.code}
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
            "full_branch_comparison_and_protected_holdout": "RESEARCH_CAMPAIGNS_SEPARATE;PROTECTED_HOLDOUT_PENDING",
        }
    from .local_usage import summary
    from .research_memory import memory_status
    from .training_window import status as training_window

    with db.pool.connection() as c:
        window = training_window(c)

    return {
        "token_usage": summary(db),
        "training_window": window,
        "research_memory": memory_status(db),
        "training_soaks": db.rows("""SELECT r.*,count(s.sample_at) AS samples,max(s.sample_at) AS last_sample,
            count(s.sample_at) FILTER(WHERE (s.payload->>'review_required')::boolean) AS flagged_samples
            FROM research_soaks r LEFT JOIN research_soak_samples s ON s.soak_id=r.id
            GROUP BY r.id ORDER BY r.started_at DESC LIMIT 10"""),
        "code_digest": code_identity(),
        "mail_schedule": db.rows("SELECT payload FROM report_state"),
        "mail_delivery": db.rows("SELECT state,count(*) AS n FROM mail_deliveries GROUP BY state"),
        "host_capacity": host_capacity,
        "runtime_policy": {
            "local_billing": False,
            "usage_admission_limits": False,
            "research_lifetime_limit": None,
            "research_agent": db.settings.research_agent,
            "research_pipeline_depth": db.settings.research_pipeline_depth,
            "research_validation": db.settings.research_validation,
            "training_threads_per_origin": db.settings.training_threads,
            "origin_processes": db.settings.origin_processes,
            "training_cpus": min(20, db.settings.training_threads * db.settings.origin_processes),
            "inference_cpus": db.settings.inference_threads,
            "inference_threads_when_compute_pending": db.settings.inference_busy_threads,
            "blas_threads": 1,
            "planner_cpus": 1,
            "cpu_pool": db.settings.cpu_pool,
            "process_affinity": sorted(os.sched_getaffinity(0)),
            "host_reserved_cpus": "20-21",
        },
        "loops": loops,
        "jobs": db.rows("SELECT state,kind,count(*) AS count FROM jobs GROUP BY state,kind"),
        "workers": db.rows("SELECT * FROM worker_status ORDER BY id"),
        "draws": db.rows("SELECT count(*) AS count,max(issue) AS latest_issue FROM draws")[0],
        "models": db.rows("SELECT count(*) AS count FROM models")[0]["count"],
        "new_label_consumptions": db.rows("SELECT count(*) AS count FROM consumptions WHERE newly_consumed")[
            0
        ]["count"],
        "owned_artifact_bytes": artifacts.usage(),
        "artifact_quota_bytes": None,
        "artifact_gc_watermark_bytes": db.settings.quota_bytes,
        "database_bytes": db.rows("SELECT pg_database_size(current_database()) AS bytes")[0]["bytes"],
        "storage_scope": "P3 registered Next artifacts, PostgreSQL/WAL, inference cache, images/log bounds and shared build-cache upper bound",
        "programs": db.rows(
            "SELECT id,state,generation,current_campaign,next_due,last_reason,launched_today FROM research_programs"
        ),
        "active_reservations": db.rows(
            "SELECT job_id,lane,cpu_cap,wall_cap,write_reserved,written FROM resource_reservations WHERE state='ACTIVE'"
        ),
        "resource_wait": db.rows("SELECT payload FROM resource_state"),
        "maintenance": db.rows("SELECT payload FROM maintenance_state"),
        "retired_research": db.rows("SELECT * FROM research_rollups"),
        "research_campaigns": db.rows(
            "SELECT id,status,selected_node,updated_at FROM research_campaigns ORDER BY created_at"
        ),
        "full_autonomous_research": {
            "backend": "LOCAL" if os.getenv("DEHPS_NEXT_RESEARCH_URL") else "NOT_CONFIGURED",
            "model": os.getenv("DEHPS_NEXT_RESEARCH_MODEL", "qwen3:1.7b"),
            "inference_calls": db.rows(
                "SELECT state,count(*) AS count FROM research_model_calls GROUP BY state"
            ),
            "value_model_versions": db.rows("SELECT count(*) AS n FROM research_policy_versions")[0]["n"],
            "scope": "BOUNDED_DEVELOPMENT_CAMPAIGNS;NO_LLM_WEIGHT_FINETUNING;NO_FORWARD_PROOF",
        },
        "legacy_access": "NONE",
    }
