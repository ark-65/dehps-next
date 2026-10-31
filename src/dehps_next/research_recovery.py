"""Audited successors for failed frozen work; never rewrite old attempts or contracts."""

import json

from psycopg.types.json import Jsonb

from .domain import digest, timestamp
from .errors import DomainError
from .release import numeric_identity
from .research import Research
from .research_memory import archive_campaign, compact
from .scores import decode, encode


def backfill(db):
    contracts = set()
    ids = db.rows("SELECT id FROM research_campaigns ORDER BY created_at")
    for row in ids:
        with db.pool.connection() as c, c.transaction():
            contracts.add(archive_campaign(c, row["id"]))
    for contract in contracts:
        with db.pool.connection() as c, c.transaction():
            compact(c, contract, force=True, reason="EXISTING_FACTS_BACKFILL")
    return {
        "campaigns": len(ids),
        "contracts": len(contracts),
        "note": "Only surviving factual records archived;previously retired details not invented",
    }


def recover_failed(db, artifacts):
    results = []
    failed = db.rows(
        """SELECT j.id,j.checkpoint,n.spec,n.id AS old_node,r.dataset_id,r.protocol,r.config,
        ds.artifact AS dataset_artifact FROM jobs j JOIN research_nodes n ON n.id=j.research_node_id
        JOIN research_campaigns r ON r.id=n.campaign_id JOIN datasets ds ON ds.id=r.dataset_id
        WHERE j.state='FAILED' AND j.error_code='ARTIFACT_CORRUPT'
          AND NOT EXISTS(SELECT 1 FROM research_recoveries x WHERE x.old_job_id=j.id)
        ORDER BY j.updated_at"""
    )
    for old in failed:
        snapshot = json.loads(artifacts.read(old["dataset_artifact"]))
        expected_identity = digest([old["spec"], old["protocol"]["digest"], snapshot["cutoff"]])
        catalog = (
            db.rows(
                "SELECT ref FROM artifact_catalog WHERE path=%s AND state!='DELETED'",
                (old["checkpoint"]["path"],),
            )
            if old["checkpoint"]
            else []
        )
        evidence = {
            "old_job": old["id"],
            "old_node": old["old_node"],
            "old_reference": old["checkpoint"],
            "validated_reference": None,
            "reused_origins": 0,
            "mode": "FRESH_REFIT",
            "old_facts_preserved": True,
        }
        saved = None
        try:
            if catalog:
                ref = catalog[0]["ref"]
                candidate = decode(artifacts.read(ref))
                rows = candidate["rows"]
                origins = old["protocol"]["origins"]
                if old["config"].get("numeric_digest") != numeric_identity():
                    raise DomainError("RECOVERY_NUMERIC_CHANGED", "Cannot reuse different numeric work")
                if old["config"].get("numeric_threads") != db.settings.training_threads:
                    raise DomainError("RECOVERY_THREADS_CHANGED", "Cannot reuse different frozen threads")
                if candidate["identity"] != expected_identity or not rows:
                    raise DomainError("RECOVERY_IDENTITY", "Checkpoint identity differs")
                if [r["origin"] for r in rows] != origins[: len(rows)]:
                    raise DomainError("RECOVERY_PREFIX", "Only a contiguous original prefix may be reused")
                for row in rows:
                    index = row["origin"]
                    actual = snapshot["rows"][index]
                    prior = snapshot["rows"][index - 1]
                    if (
                        row["issue"] != actual["issue"]
                        or row["training_through"] != prior["issue"]
                        or timestamp(prior["available_at"]) >= timestamp(actual["draw_at"])
                        or not row["parameter_updated"]
                    ):
                        raise DomainError("RECOVERY_PROVENANCE", "Invalid prior-only origin provenance")
                    red, blue = row["red_probabilities"], row["blue_probabilities"]
                    if (
                        len(red) != 33
                        or len(blue) != 16
                        or any(not 0 <= v <= 1 for v in red + blue)
                        or abs(sum(blue) - 1) > 1e-5
                        or not row["weight_digest"]
                    ):
                        raise DomainError("RECOVERY_PROBABILITIES", "Invalid frozen probabilities")
                saved = candidate
                evidence.update(validated_reference=ref, reused_origins=len(rows), mode="VERIFIED_PREFIX")
        except (DomainError, ValueError, KeyError, OSError) as exc:
            evidence["discard_reason"] = getattr(exc, "code", type(exc).__name__)
        # Fix the old snapshot and protocol by checking the successor before dispatch.
        name = "recovery-" + old["id"][:24]
        with db.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(740134)")
            if c.execute("SELECT 1 FROM research_recoveries WHERE old_job_id=%s", (old["id"],)).fetchone():
                continue
            Research(db, artifacts).create(
                name,
                root_spec=old["spec"],
                max_nodes=2,
                recovery_source=evidence,
                recovery_dataset=old["dataset_id"],
                recovery_protocol=old["protocol"],
                connection=c,
            )
            new = c.execute("SELECT * FROM research_campaigns WHERE id=%s", (name,)).fetchone()
            if (
                new["dataset_id"] != old["dataset_id"]
                or new["protocol"]["digest"] != old["protocol"]["digest"]
            ):
                raise DomainError("RECOVERY_DATA_CHANGED", "Original snapshot/protocol must remain frozen")
            node = c.execute("SELECT id FROM research_nodes WHERE campaign_id=%s", (name,)).fetchone()["id"]
            if saved:
                ref = artifacts.write(encode(saved["rows"], saved["identity"]), category="checkpoints")
                artifacts.read(ref)
                c.execute(
                    "UPDATE jobs SET checkpoint=%s WHERE research_node_id=%s AND kind='RESEARCH_EVALUATE'",
                    (Jsonb(ref), node),
                )
            c.execute(
                "INSERT INTO research_recoveries VALUES(%s,%s,%s,%s,now())",
                (old["id"], name, node, Jsonb(evidence)),
            )
            Research.decision(c, name, node, "RECOVERY_REGISTERED", evidence)
            results.append({"campaign": name, **evidence})
    return results
