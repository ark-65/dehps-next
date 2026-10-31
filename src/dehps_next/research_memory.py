"""Compact recipe memory, independent of controller releases and retired model artifacts."""

from psycopg.types.json import Jsonb

from .domain import digest
from .errors import DomainError
from .release import numeric_identity


def untried_specs(db, dataset, specs, *, connection=None):
    """Probe exact indexed identities in bounded batches; never load the complete memory."""
    identities = {digest(spec): spec for spec in specs}
    if not identities:
        return []
    sql = """SELECT spec_digest FROM research_recipe_memory
        WHERE dataset_id=%s AND numeric_digest=%s AND spec_digest=ANY(%s)
          AND verdict IS DISTINCT FROM 'STALE_UNTRAINED'"""
    params = (dataset, numeric_identity(), list(identities))
    rows = connection.execute(sql, params).fetchall() if connection else db.rows(sql, params)
    known = {r["spec_digest"] for r in rows}
    return [spec for key, spec in identities.items() if key not in known]


def feedback_contract(campaign):
    return digest(
        [
            campaign["dataset_id"],
            campaign["protocol"]["digest"],
            campaign["config"].get("numeric_digest", numeric_identity()),
            campaign["config"].get("numeric_threads", 2),
        ]
    )


def archive_node(c, node_id, *, periods=None, origin_provenance=None):
    """Archive factual paired feedback before optional graphs can be retired."""
    node = c.execute(
        """SELECT n.*,r.dataset_id,r.protocol,r.config FROM research_nodes n
        JOIN research_campaigns r ON r.id=n.campaign_id WHERE n.id=%s""",
        (node_id,),
    ).fetchone()
    if not node or not node["evaluation"]:
        return None
    contract = feedback_contract(node)
    hypothesis = node["hypothesis"]
    evaluation = node["evaluation"]
    parent = (
        c.execute(
            "SELECT evaluation->'summary' AS summary FROM research_nodes WHERE id=%s", (node["parent_id"],)
        ).fetchone()
        if node["parent_id"]
        else None
    )
    payload = {
        "campaign": node["campaign_id"],
        "path": node["path"],
        "verdict": node["status"],
        "summary": evaluation["summary"],
        "business": evaluation.get("business"),
        "parent_summary": parent["summary"] if parent else None,
        "decision": node["decision"],
        "execution": evaluation["execution"],
        "parent_id": node["parent_id"],
        "completed_at": node["completed_at"].isoformat(),
        "parameter_changes": hypothesis.get("parameter_changes", {}),
        "cited_feedback": hypothesis.get("cited_feedback"),
        "hypothesis": hypothesis.get("hypothesis"),
        "risk": hypothesis.get("falsification"),
        "review_evidence": hypothesis.get("review_evidence"),
        "references": {k: evaluation.get(k) for k in ("scores", "publication_anchor")},
        "evidence": evaluation["evidence"],
        "period_outcomes": periods,
        "origin_provenance": origin_provenance,
        "detail_coverage": "FROZEN_PER_PERIOD" if periods is not None else "LEGACY_AGGREGATES_AND_REFERENCES",
    }
    insert_event(c, node, contract, node_id + ":evaluation", "EVALUATION", payload)
    return contract


def insert_event(c, campaign, contract, key, kind, payload, node_id=None, spec=None):
    # Acquire before nextval: a committed head must not jump over an uncommitted
    # lower sequence from another producer of the same feedback contract.
    c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,740142))", (contract,))
    c.execute(
        """INSERT INTO research_memory_events(event_key,contract,dataset_id,numeric_digest,
        protocol_digest,numeric_threads,node_id,parent_id,spec,kind,payload)
        VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(event_key) DO NOTHING""",
        (
            key,
            contract,
            campaign["dataset_id"],
            campaign["config"].get("numeric_digest", numeric_identity()),
            campaign["protocol"]["digest"],
            campaign["config"].get("numeric_threads", 2),
            node_id or campaign.get("id"),
            campaign.get("parent_id"),
            Jsonb(spec or campaign.get("spec")) if spec or campaign.get("spec") else None,
            kind,
            Jsonb(payload),
        ),
    )


def archive_campaign(c, campaign_id):
    campaign = c.execute("SELECT * FROM research_campaigns WHERE id=%s", (campaign_id,)).fetchone()
    contract = feedback_contract(campaign)
    for n in c.execute("SELECT id FROM research_nodes WHERE campaign_id=%s", (campaign_id,)).fetchall():
        archive_node(c, n["id"])
    for failed in c.execute(
        """SELECT a.id,a.error_code,a.started_at,a.ended_at,j.id AS job,n.id AS node,n.spec
        FROM attempts a JOIN jobs j ON j.id=a.job_id JOIN research_nodes n ON n.id=j.research_node_id
        WHERE n.campaign_id=%s AND a.state IN ('FAILED','LOST')""",
        (campaign_id,),
    ).fetchall():
        insert_event(
            c,
            campaign,
            contract,
            "attempt:" + failed["id"],
            "EXECUTION_FAILURE",
            {
                "campaign": campaign_id,
                "job": failed["job"],
                "error_code": failed["error_code"],
                "started_at": str(failed["started_at"]),
                "ended_at": str(failed["ended_at"]),
                "model_regression": False,
            },
            node_id=failed["node"],
            spec=failed["spec"],
        )
    calls = c.execute(
        """SELECT state,count(*) AS n,coalesce(sum(usage_input_tokens),0)::bigint AS input,
        coalesce(sum(usage_output_tokens),0)::bigint AS output,
        count(*) FILTER(WHERE usage_input_tokens IS NULL OR usage_output_tokens IS NULL) AS missing
        FROM research_model_calls WHERE campaign_id=%s GROUP BY state""",
        (campaign_id,),
    ).fetchall()
    receipts = c.execute(
        """SELECT id,stage,state,model,model_digest,request,response,metrics,
        usage_input_tokens,usage_output_tokens,created_at::text AS created_at
        FROM research_model_calls WHERE campaign_id=%s ORDER BY id""",
        (campaign_id,),
    ).fetchall()
    dataset = c.execute("SELECT * FROM datasets WHERE id=%s", (campaign["dataset_id"],)).fetchone()
    insert_event(
        c,
        campaign,
        contract,
        "campaign:" + campaign_id,
        "CAMPAIGN_ARCHIVE",
        {
            "campaign": campaign_id,
            "config": campaign["config"],
            "protocol": campaign["protocol"],
            "dataset": {
                "id": dataset["id"],
                "cutoff": dataset["cutoff"].isoformat(),
                "through_issue": dataset["through_issue"],
                "sample_count": dataset["sample_count"],
                "artifact": dataset["artifact"],
            },
            "selected_node": campaign["selected_node"],
            "status": campaign["status"],
            "calls": calls,
            "call_receipts": receipts,
            "detail_policy": "OPTIONAL_FILES_MAY_RETIRE;PAIRED_FACTS_AND_EXACT_RECIPE_MEMORY_PERSIST",
        },
    )
    return contract


def compact(c, contract, *, threshold=16384, reason="THRESHOLD", force=False):
    """Publish a verified immutable summary and its cursor in the same transaction."""
    c.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,740142))", (contract,))
    head = c.execute("SELECT * FROM research_memory_heads WHERE contract=%s", (contract,)).fetchone()
    cursor = head["cursor"] if head else 0
    delta = c.execute(
        "SELECT count(*) AS n,max(seq) AS cursor FROM research_memory_events WHERE contract=%s AND seq>%s",
        (contract, cursor),
    ).fetchone()
    if head and not force and delta["n"] < threshold:
        return c.execute(
            "SELECT * FROM research_memory_snapshots WHERE contract=%s AND version=%s",
            (contract, head["version"]),
        ).fetchone()
    cursor = delta["cursor"] or cursor
    totals = c.execute(
        "SELECT kind,count(*) AS n FROM research_memory_events WHERE contract=%s AND seq<=%s GROUP BY kind",
        (contract, cursor),
    ).fetchall()
    records = c.execute(
        """SELECT seq,node_id,spec,payload-'period_outcomes'-'origin_provenance' AS payload FROM research_memory_events
        WHERE contract=%s AND seq<=%s AND kind='EVALUATION'
        ORDER BY seq DESC LIMIT 6""",
        (contract, cursor),
    ).fetchall()
    improvement = c.execute(
        """SELECT seq,node_id,spec,payload-'period_outcomes'-'origin_provenance' AS payload FROM research_memory_events WHERE contract=%s AND seq<=%s
        AND kind='EVALUATION' AND payload->>'verdict'='ACCEPT_IMPROVEMENT' ORDER BY seq DESC LIMIT 1""",
        (contract, cursor),
    ).fetchone()
    pending = c.execute(
        """SELECT n.id,n.spec,j.kind,j.state,j.checkpoint,j.error_code FROM jobs j
        JOIN research_nodes n ON n.id=j.research_node_id JOIN research_campaigns r ON r.id=n.campaign_id
        WHERE r.dataset_id=(SELECT dataset_id FROM research_memory_events WHERE contract=%s LIMIT 1)
        AND j.state IN ('READY','RUNNING') ORDER BY j.created_at,j.id LIMIT 16""",
        (contract,),
    ).fetchall()
    failures = c.execute(
        """SELECT seq,node_id,spec,payload FROM research_memory_events WHERE contract=%s AND seq<=%s
        AND kind='EXECUTION_FAILURE' ORDER BY seq DESC LIMIT 6""",
        (contract, cursor),
    ).fetchall()
    version = head["version"] + 1 if head else 1
    payload = {
        "version": version,
        "contract": contract,
        "source_range": [1, cursor],
        "reason": reason,
        "counts": {r["kind"]: r["n"] for r in totals},
        "recent_feedback": records,
        "latest_improvement": improvement,
        "execution_failures": failures,
        "pending_at_compaction": pending,
        "goal": "Incremental paired red5+ Top100 and blueTop1;100 chronological issues with nested50/10",
        "unresolved": "Tradeoffs and inconclusive evidence remain unresolved;no forward improvement established",
        "next": "Retrieve relevant exact feedback;select novel recipes;resume durable tasks before adding work",
        "evidence": "DETERMINISTIC_FACT_SUMMARY;NOT_NEW_TRAINING_OR_PREDICTIVE_EVIDENCE",
    }
    sha = digest(payload)
    c.execute(
        "INSERT INTO research_memory_snapshots(contract,version,cursor,source_count,payload,sha256) VALUES(%s,%s,%s,%s,%s,%s)",
        (contract, version, cursor, sum(r["n"] for r in totals), Jsonb(payload), sha),
    )
    row = c.execute(
        "SELECT * FROM research_memory_snapshots WHERE contract=%s AND version=%s", (contract, version)
    ).fetchone()
    if digest(row["payload"]) != row["sha256"]:
        raise DomainError("MEMORY_SNAPSHOT_CORRUPT", "Keep the previous memory head")
    c.execute(
        """INSERT INTO research_memory_heads VALUES(%s,%s,%s) ON CONFLICT(contract)
        DO UPDATE SET version=excluded.version,cursor=excluded.cursor""",
        (contract, version, cursor),
    )
    return row


def recall(db, campaign, *, force=False, reason="THRESHOLD"):
    with db.pool.connection() as c, c.transaction():
        row = compact(
            c,
            feedback_contract(campaign),
            threshold=db.settings.memory_compact_records,
            reason=reason,
            force=force,
        )
        return {
            "contract": row["contract"],
            "version": row["version"],
            "cursor": row["cursor"],
            "sha256": row["sha256"],
            "source_count": row["source_count"],
            "goal": row["payload"]["goal"],
            "next": row["payload"]["next"],
            "evidence": row["payload"]["evidence"],
        }


def compact_due(db):
    due = db.rows(
        """SELECT e.contract FROM research_memory_events e
        LEFT JOIN research_memory_heads h ON h.contract=e.contract
        WHERE e.seq>coalesce(h.cursor,0) GROUP BY e.contract HAVING count(*)>=%s LIMIT 8""",
        (db.settings.memory_compact_records,),
    )
    for row in due:
        with db.pool.connection() as c, c.transaction():
            compact(c, row["contract"], threshold=db.settings.memory_compact_records)
    return len(due)


def memory_status(db):
    return {
        "heads": db.rows("""SELECT h.contract,h.version,h.cursor,s.source_count,s.sha256,s.created_at,
            s.payload->>'reason' AS reason FROM research_memory_heads h JOIN research_memory_snapshots s
            ON s.contract=h.contract AND s.version=h.version ORDER BY s.created_at DESC"""),
        "durable_events": db.rows("SELECT kind,count(*) AS count FROM research_memory_events GROUP BY kind"),
        "exact_recipes": db.rows("SELECT count(*) AS n FROM research_recipe_memory")[0]["n"],
        "compaction_threshold": db.settings.memory_compact_records,
        "threshold_action": "PERSIST_COMPACT_CONTINUE;NO_CAPACITY_STOP",
        "progress": progress_status(db),
        "progress_scope": "SURVIVING_ARCHIVED_EVALUATION_RECEIPTS;COMPACTION_AND_REUSED_ORIGINS_NOT_NEW_FITS",
        "search_batches": db.rows("""SELECT DISTINCT ON(dataset_id,numeric_digest,topic)
            dataset_id,numeric_digest,topic,generation,jsonb_array_length(candidates) AS registered,
            basis->>'neighbor_count' AS neighbors,basis->>'global_count' AS global_candidates,created_at
            FROM research_search_batches ORDER BY dataset_id,numeric_digest,topic,generation DESC"""),
        "recoveries": db.rows(
            "SELECT old_job_id,new_campaign_id,evidence,created_at FROM research_recoveries"
        ),
    }


def progress_status(db, *, since="1970-01-01T00:00:00+00:00"):
    return db.rows(
        """WITH facts AS (
        SELECT e.*,(payload->'execution'->>'origin_fits_executed_this_attempt')::bigint AS fits,
          (payload->'execution'->>'gradient_steps_executed_this_attempt')::bigint AS steps,
          EXISTS(SELECT 1 FROM research_memory_events p WHERE p.node_id=e.node_id AND p.kind='FIT_PROGRESS') AS has_prefix
        FROM research_memory_events e WHERE kind IN ('EVALUATION','FIT_PROGRESS')
          AND (payload->>'completed_at')::timestamptz>=%s)
        SELECT max((payload->>'completed_at')::timestamptz)
          FILTER(WHERE coalesce(steps,(payload->>'gradient_steps')::bigint)>0) AS last_actual_fit_at,
          coalesce(sum(CASE WHEN kind='FIT_PROGRESS' THEN (payload->>'new_origins')::bigint
            WHEN NOT has_prefix THEN fits ELSE 0 END),0)::bigint AS committed_fresh_origins,
          coalesce(sum(CASE WHEN kind='FIT_PROGRESS' THEN (payload->>'gradient_steps')::bigint
            WHEN has_prefix THEN steps-fits*(spec->>'epochs')::int ELSE steps END),0)::bigint AS committed_gradient_steps,
          coalesce(sum((payload->'execution'->>'resumed_origins')::bigint),0)::bigint AS reused_origins
        FROM facts""",
        (since,),
    )[0]


def remember(c, dataset, numeric, spec, verdict=None, summary=None):
    identity = digest(spec)
    c.execute(
        """INSERT INTO research_recipe_memory(dataset_id,numeric_digest,spec_digest,spec,verdict,summary)
        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT(dataset_id,numeric_digest,spec_digest)
        DO UPDATE SET verdict=CASE
          WHEN excluded.verdict IS NULL AND research_recipe_memory.verdict='STALE_UNTRAINED' THEN NULL
          ELSE coalesce(excluded.verdict,research_recipe_memory.verdict) END,
        summary=coalesce(excluded.summary,research_recipe_memory.summary),last_seen_at=now()""",
        (dataset, numeric, identity, Jsonb(spec), verdict, Jsonb(summary) if summary else None),
    )


def known_specs(db, dataset):
    return [
        r["spec"]
        for r in db.rows(
            "SELECT spec FROM research_recipe_memory WHERE dataset_id=%s AND numeric_digest=%s AND verdict IS DISTINCT FROM 'STALE_UNTRAINED' ORDER BY last_seen_at,spec_digest",
            (dataset, numeric_identity()),
        )
    ]


def adopt_numeric(db, release, reason):
    if len(release) != 64 or len(reason) < 24:
        raise DomainError("NUMERIC_REVIEW_REQUIRED", "Explicitly audit numerical equivalence before reuse")
    numeric = numeric_identity()
    with db.pool.connection() as c, c.transaction():
        c.execute("SELECT pg_advisory_xact_lock(740134)")
        existing = c.execute(
            "SELECT numeric_digest FROM numeric_releases WHERE release_digest=%s", (release,)
        ).fetchone()
        if existing and existing["numeric_digest"] != numeric:
            raise DomainError("NUMERIC_REVIEW_CONFLICT", "An audited release cannot be silently remapped")
        c.execute(
            "INSERT INTO numeric_releases VALUES(%s,%s,%s,now()) ON CONFLICT DO NOTHING",
            (release, numeric, reason),
        )
        nodes = c.execute(
            """SELECT n.*,r.dataset_id FROM research_nodes n JOIN research_campaigns r ON r.id=n.campaign_id
            WHERE r.config->>'code_digest'=%s AND n.evaluation IS NOT NULL ORDER BY n.completed_at""",
            (release,),
        ).fetchall()
        for node in nodes:
            remember(
                c, node["dataset_id"], numeric, node["spec"], node["status"], node["evaluation"]["summary"]
            )
    return {"release": release, "numeric_digest": numeric, "reviewed_nodes": len(nodes)}
