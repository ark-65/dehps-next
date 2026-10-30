"""Compact recipe memory, independent of controller releases and retired model artifacts."""

from psycopg.types.json import Jsonb

from .domain import digest
from .errors import DomainError
from .release import numeric_identity


def remember(c, dataset, numeric, spec, verdict=None, summary=None):
    identity = digest(spec)
    if (
        not c.execute(
            "SELECT 1 FROM research_recipe_memory WHERE dataset_id=%s AND numeric_digest=%s AND spec_digest=%s",
            (dataset, numeric, identity),
        ).fetchone()
        and c.execute(
            "SELECT count(*) AS n FROM research_recipe_memory WHERE dataset_id=%s AND numeric_digest=%s",
            (dataset, numeric),
        ).fetchone()["n"]
        >= 16384
    ):
        raise DomainError("SEARCH_MEMORY_CAPACITY", "Bounded recipe memory exhausted for this snapshot")
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
