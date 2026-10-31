"""Reference-safe mark/grace/recheck/sweep and bounded research-detail retirement."""

import base64
import hashlib
import os
from datetime import timedelta

from psycopg.types.json import Jsonb

from .domain import now
from .errors import DomainError
from .resources import TERMINAL

GRACE_SECONDS = 60
DETAIL_DAYS = 7


def refs(value):
    if isinstance(value, dict):
        if {"path", "sha256", "bytes"} <= set(value):
            yield value
        else:
            for child in value.values():
                yield from refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from refs(child)


class Lifecycle:
    def __init__(self, db, artifacts):
        self.db, self.artifacts = db, artifacts

    def recover_quarantine(self):
        directory = self.artifacts.path(".gc-quarantine")
        if not directory.exists():
            return
        for file in directory.iterdir():
            if file.is_symlink() or not file.is_file():
                raise DomainError("GC_QUARANTINE_PATH", "Invalid quarantine entry")
            relative = base64.urlsafe_b64decode(file.name.encode()).decode()
            target = self.artifacts.path(relative)
            row = self.db.rows("SELECT state FROM artifact_catalog WHERE path=%s", (relative,))
            if row and row[0]["state"] != "DELETED" and not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(file, target)
            else:
                file.unlink()

    def reachability(self, c, pressure=False):
        protected, registered = set(), {}
        for file in self.artifacts.root.rglob(".pending-*"):
            self.artifacts.path(str(file.relative_to(self.artifacts.root)))
            if file.is_file() and now().timestamp() - file.stat().st_mtime > 86400:
                data = file.read_bytes()
                if len(data) > self.db.settings.artifact_bytes:
                    raise DomainError("ORPHAN_SIZE", "Owned pending file exceeds the artifact contract")
                ref = {
                    "path": str(file.relative_to(self.artifacts.root)),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
                c.execute(
                    "INSERT INTO artifact_catalog(path,ref,category,created_at,writer_until) VALUES(%s,%s,'cache',to_timestamp(%s),now()) ON CONFLICT DO NOTHING",
                    (ref["path"], Jsonb(ref), file.stat().st_mtime),
                )

        def add(value, protect):
            for ref in refs(value):
                self.artifacts.path(ref["path"])
                registered[ref["path"]] = ref
                if protect:
                    protected.add(ref["path"])

        for table, column in (("sources", "artifact"), ("models", "artifact")):
            for row in c.execute(f"SELECT {column} FROM {table}"):
                add(row[column], True)
        for row in c.execute("SELECT evidence FROM forecast_selections"):
            add(row["evidence"], True)
        for row in c.execute("SELECT evidence FROM forecast_final_selections"):
            add(row["evidence"], True)
        core_datasets = {r["dataset_id"] for r in c.execute("SELECT DISTINCT dataset_id FROM cycles")}
        campaigns = c.execute("SELECT * FROM research_campaigns ORDER BY created_at DESC").fetchall()
        keep_campaigns = {
            r["id"]
            for r in campaigns
            if r["status"] not in TERMINAL and not r["status"].startswith("BLOCKED_")
        }
        keep_campaigns.update(r["id"] for r in campaigns[:2])
        # Even a blocked task may still be resumed: all READY/RUNNING inputs remain roots.
        keep_campaigns.update(
            r["campaign_id"]
            for r in c.execute(
                "SELECT DISTINCT n.campaign_id FROM jobs j JOIN research_nodes n ON n.id=j.research_node_id WHERE j.state IN ('READY','RUNNING')"
            )
        )
        recent = {r["id"] for r in campaigns if r["updated_at"] > now() - timedelta(days=DETAIL_DAYS)}
        keep_artifacts = keep_campaigns | (set() if pressure else recent)
        research_datasets = {r["dataset_id"] for r in campaigns if r["id"] in keep_artifacts}
        for row in c.execute("SELECT id,artifact FROM datasets"):
            add(row["artifact"], row["id"] in core_datasets | research_datasets)
        for row in c.execute("SELECT campaign_id,anchor,evaluation,hypothesis FROM research_nodes"):
            add(row, row["campaign_id"] in keep_artifacts)
        for row in c.execute("SELECT checkpoint FROM jobs WHERE checkpoint IS NOT NULL"):
            add(row["checkpoint"], True)
        newest_policies = {
            r["id"] for r in c.execute("SELECT id FROM research_policy_versions ORDER BY id DESC LIMIT 2")
        }
        for row in c.execute("SELECT * FROM research_policy_versions"):
            add(row["artifact"], row["id"] in newest_policies or row["campaign_id"] in keep_artifacts)
        for row in c.execute("SELECT campaign_id,request,response FROM research_model_calls"):
            add(row, row["campaign_id"] in keep_artifacts)
        for row in c.execute("SELECT artifact FROM research_score_cache"):
            add(row["artifact"], True)
        for ref in registered.values():
            c.execute(
                "INSERT INTO artifact_catalog(path,ref,category,writer_until) VALUES(%s,%s,%s,now()) ON CONFLICT DO NOTHING",
                (ref["path"], Jsonb(ref), ref["path"].rsplit("/", 1)[0]),
            )
        return protected, keep_campaigns

    def retire_details(self, c, keep):
        # Fixed-size rollups replace old research graph/attempt/call metadata, never formal facts.
        c.execute("SET LOCAL dehps_next.retirement='on'")
        eligible = c.execute(
            """SELECT * FROM research_campaigns WHERE id!=ALL(%s)
            AND status=ANY(%s) AND (updated_at<now()-interval '90 days' OR
            id IN (SELECT id FROM research_campaigns ORDER BY created_at DESC OFFSET 256))
            ORDER BY created_at LIMIT 16""",
            (list(keep), list(TERMINAL) + ["BLOCKED_DUPLICATE_RESEARCH_DIRECTION"]),
        ).fetchall()
        compact_contracts = set()
        for campaign in eligible:
            identity = campaign["id"]
            if c.execute(
                "SELECT 1 FROM jobs j JOIN research_nodes n ON n.id=j.research_node_id WHERE n.campaign_id=%s AND j.state IN ('READY','RUNNING')",
                (identity,),
            ).fetchone():
                continue
            if c.execute(
                "SELECT 1 FROM research_policy_versions WHERE campaign_id=%s AND id IN (SELECT id FROM research_policy_versions ORDER BY id DESC LIMIT 2)",
                (identity,),
            ).fetchone():
                continue
            counts = c.execute(
                "SELECT count(*) AS n FROM research_nodes WHERE campaign_id=%s", (identity,)
            ).fetchone()["n"]
            events = c.execute(
                "SELECT count(*) AS n FROM research_decisions WHERE campaign_id=%s", (identity,)
            ).fetchone()["n"]
            from .research_memory import archive_campaign

            compact_contracts.add(archive_campaign(c, identity))
            topic = campaign["topic"] if campaign["program_id"] else "manual"
            c.execute(
                """INSERT INTO research_rollups(topic,campaigns,nodes,decisions) VALUES(%s,1,%s,%s)
                ON CONFLICT(topic) DO UPDATE SET campaigns=research_rollups.campaigns+1,
                nodes=research_rollups.nodes+excluded.nodes,decisions=research_rollups.decisions+excluded.decisions,updated_at=now()""",
                (topic, counts, events),
            )
            c.execute("DELETE FROM research_model_calls WHERE campaign_id=%s", (identity,))
            c.execute("DELETE FROM research_policy_versions WHERE campaign_id=%s", (identity,))
            c.execute("DELETE FROM research_decisions WHERE campaign_id=%s", (identity,))
            c.execute(
                "DELETE FROM resource_reservations WHERE job_id IN (SELECT j.id FROM jobs j JOIN research_nodes n ON n.id=j.research_node_id WHERE n.campaign_id=%s) AND state!='ACTIVE'",
                (identity,),
            )
            c.execute(
                "DELETE FROM attempts WHERE job_id IN (SELECT j.id FROM jobs j JOIN research_nodes n ON n.id=j.research_node_id WHERE n.campaign_id=%s)",
                (identity,),
            )
            c.execute(
                "DELETE FROM jobs WHERE research_node_id IN (SELECT id FROM research_nodes WHERE campaign_id=%s)",
                (identity,),
            )
            c.execute("DELETE FROM research_nodes WHERE campaign_id=%s", (identity,))
            c.execute("DELETE FROM research_campaigns WHERE id=%s", (identity,))
        from .research_memory import compact

        for contract in compact_contracts:
            compact(c, contract, reason="BEFORE_GRAPH_RETIREMENT", force=True)
        # Exact recipe identities and paired memories survive every graph/context compaction.
        c.execute("DELETE FROM local_token_days WHERE day<current_date-32")
        # Preserve lifetime counts while retaining only a bounded recent accounting ledger.
        old = c.execute(
            "DELETE FROM resource_days WHERE day<current_date-32 RETURNING spent,calls"
        ).fetchall()
        c.execute(
            "UPDATE resource_totals SET charged=charged+%s,calls=calls+%s WHERE id=1",
            (sum(r["spent"] for r in old), sum(r["calls"] for r in old)),
        )
        c.execute(
            "DELETE FROM resource_reservations WHERE state!='ACTIVE' AND ended_at<now()-interval '32 days'"
        )
        c.execute("DELETE FROM worker_status WHERE heartbeat_at<now()-interval '7 days' AND state!='RUNNING'")
        c.execute("""DELETE FROM attempts WHERE id IN (SELECT id FROM
            (SELECT a.id,row_number() OVER(PARTITION BY a.job_id ORDER BY a.started_at DESC) AS rn
            FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE j.research_node_id IS NOT NULL AND a.state!='RUNNING') ranked
            WHERE rn>32) AND id NOT IN (SELECT attempt_id FROM research_model_calls)""")
        c.execute(
            "DELETE FROM gc_receipts WHERE id IN (SELECT id FROM gc_receipts ORDER BY id DESC OFFSET 2048)"
        )
        c.execute(
            "DELETE FROM artifact_catalog WHERE state='DELETED' AND deleted_at<now()-interval '90 days'"
        )
        return len(eligible)

    def collect(self, *, apply=False):
        counts = {
            "mode": "APPLY" if apply else "DRY_RUN",
            "protected": 0,
            "candidates": 0,
            "deleted": 0,
            "deleted_bytes": 0,
            "at": now().isoformat(),
        }
        with self.artifacts.locked(), self.db.pool.connection() as c, c.transaction():
            self.recover_quarantine()
            c.execute("SELECT pg_advisory_xact_lock(740139)")
            if apply:
                c.execute(
                    "DELETE FROM research_score_cache WHERE created_at<now()-interval '7 days' OR id IN (SELECT id FROM research_score_cache ORDER BY created_at DESC OFFSET 64)"
                )
            pressure = self.artifacts.usage() >= self.db.settings.quota_bytes * 0.7
            counts["capacity_pressure"] = pressure
            protected, keep = self.reachability(c, pressure=pressure)
            counts["protected"] = len(protected)
            for row in c.execute(
                "SELECT * FROM artifact_catalog WHERE state!='DELETED' AND path!=ALL(%s) ORDER BY created_at LIMIT 4096",
                (list(protected),),
            ).fetchall():
                path = row["path"]
                pinned = row["pin_until"] and row["pin_until"] > now()
                if path in protected or pinned or row["writer_until"] > now():
                    if apply and row["candidate_at"]:
                        c.execute(
                            "UPDATE artifact_catalog SET candidate_at=NULL,state='LIVE' WHERE path=%s",
                            (path,),
                        )
                    continue
                age = (now() - row["created_at"]).total_seconds()
                ttl = 86400 if row["category"] in ("cache", "checkpoints") else DETAIL_DAYS * 86400
                if pressure and row["category"].startswith("research/"):
                    ttl = 60
                if age < ttl:
                    continue
                counts["candidates"] += 1
                if not apply:
                    continue
                if row["candidate_at"] is None:
                    c.execute(
                        "UPDATE artifact_catalog SET candidate_at=now(),state='CANDIDATE',reason='UNREFERENCED_TTL' WHERE path=%s",
                        (path,),
                    )
                    c.execute(
                        "INSERT INTO gc_receipts(path,sha256,bytes,action,reason) VALUES(%s,%s,%s,'MARK','UNREFERENCED_TTL')",
                        (path, row["ref"]["sha256"], row["ref"]["bytes"]),
                    )
                    continue
                if (now() - row["candidate_at"]).total_seconds() < GRACE_SECONDS:
                    continue
                # Claims, publication and this sweep serialize on 740139. Writers serialize on quota lock.
                file = self.artifacts.path(path)
                if file.exists():
                    self.artifacts.read(row["ref"])
                    quarantine = self.artifacts.path(".gc-quarantine")
                    quarantine.mkdir(exist_ok=True)
                    os.replace(file, quarantine / base64.urlsafe_b64encode(path.encode()).decode())
                c.execute(
                    "UPDATE artifact_catalog SET state='DELETED',deleted_at=now() WHERE path=%s", (path,)
                )
                c.execute(
                    "INSERT INTO gc_receipts(path,sha256,bytes,action,reason) VALUES(%s,%s,%s,'DELETE','RECHECKED_UNREFERENCED_TTL')",
                    (path, row["ref"]["sha256"], row["ref"]["bytes"]),
                )
                counts["deleted"] += 1
                counts["deleted_bytes"] += row["ref"]["bytes"]
            if apply:
                counts["retired_campaigns"] = self.retire_details(c, keep)
                c.execute(
                    "UPDATE resource_totals SET deleted_artifact_bytes=deleted_artifact_bytes+%s WHERE id=1",
                    (counts["deleted_bytes"],),
                )
                c.execute(
                    "INSERT INTO maintenance_state VALUES(1,%s) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                    (Jsonb(counts),),
                )
        if apply:
            with self.artifacts.locked():
                self.recover_quarantine()
        return counts
