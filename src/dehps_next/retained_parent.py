"""Accepted-parent lineage independent of optional research graphs and report qualification."""

import json

from psycopg.types.json import Jsonb

from .calendar import ZONE
from .domain import digest, timestamp
from .errors import DomainError
from .release import numeric_identity

PROGRAM = "autonomous-v2"


def register(c, artifacts, node_id):
    node = c.execute(
        """SELECT n.*,r.program_id,r.config,r.protocol,r.dataset_id,d.artifact AS dataset_artifact,
        d.through_issue,d.cutoff FROM research_nodes n JOIN research_campaigns r ON r.id=n.campaign_id
        JOIN datasets d ON d.id=r.dataset_id WHERE n.id=%s""",
        (node_id,),
    ).fetchone()
    if (
        not node
        or not node["program_id"]
        or node["status"] not in ("ACCEPT_BASELINE", "ACCEPT_IMPROVEMENT")
        or node["config"].get("study_source")
        or node["config"].get("recovery_source")
    ):
        return None
    for ref in (
        node["evaluation"]["publication_anchor"],
        node["evaluation"]["scores"],
        node["dataset_artifact"],
    ):
        artifacts.read(ref)
    c.execute("SELECT pg_advisory_xact_lock(740146)")
    head = c.execute(
        "SELECT * FROM retained_parent_heads WHERE program_id=%s FOR UPDATE", (node["program_id"],)
    ).fetchone()
    if head and head["version_id"] == node_id:
        return node_id
    if c.execute("SELECT 1 FROM retained_parent_versions WHERE id=%s", (node_id,)).fetchone():
        return node_id  # Replaying an old accepted fact must never move the head backwards.
    if head:
        current = c.execute(
            "SELECT snapshot FROM retained_parent_versions WHERE id=%s", (head["version_id"],)
        ).fetchone()["snapshot"]
        if timestamp(current["completed_at"]) > node["completed_at"]:
            return None
    snapshot = json.loads(
        json.dumps(
            {
                k: node[k]
                for k in (
                    "id",
                    "parent_id",
                    "path",
                    "campaign_id",
                    "program_id",
                    "spec",
                    "status",
                    "completed_at",
                    "evaluation",
                    "decision",
                    "anchor",
                    "config",
                    "protocol",
                    "dataset_id",
                    "dataset_artifact",
                    "through_issue",
                    "cutoff",
                )
            },
            default=lambda value: value.isoformat(),
        )
    )
    previous = head["version_id"] if head else None
    c.execute(
        "INSERT INTO retained_parent_versions(id,program_id,previous_version,snapshot) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        (node_id, node["program_id"], previous, Jsonb(snapshot)),
    )
    c.execute(
        """INSERT INTO retained_parent_heads(program_id,version_id,previous_version) VALUES(%s,%s,%s)
        ON CONFLICT(program_id) DO UPDATE SET version_id=excluded.version_id,
        previous_version=excluded.previous_version,updated_at=now()""",
        (node["program_id"], node_id, previous),
    )
    return node_id


def bootstrap(db, artifacts):
    with db.pool.connection() as c, c.transaction():
        nodes = c.execute("""SELECT r.selected_node FROM research_programs p
            JOIN research_campaigns r ON r.id=p.current_campaign WHERE p.state!='DISABLED'""").fetchall()
        return [value for row in nodes if (value := register(c, artifacts, row["selected_node"]))]


def resolve(db, artifacts, target):
    rows = db.rows(
        """WITH RECURSIVE chain AS (
        SELECT v.*,0 AS depth FROM retained_parent_heads h JOIN retained_parent_versions v ON v.id=h.version_id
        WHERE h.program_id=%s UNION ALL SELECT v.*,c.depth+1 FROM chain c
        JOIN retained_parent_versions v ON v.id=c.previous_version WHERE c.depth<1)
        SELECT * FROM chain WHERE (snapshot->>'completed_at')::timestamptz<=%s ORDER BY depth""",
        (PROGRAM, target["prepare_time"]),
    )
    latest = db.rows(
        """SELECT issue FROM effective_draws WHERE available_at<=%s AND observed_at<=%s
        ORDER BY draw_at DESC LIMIT 1""",
        (target["prepare_time"], target["prepare_time"]),
    )[0]["issue"]
    failures = []
    for version in rows:
        node = version["snapshot"]
        if (
            node["through_issue"] != latest
            or node["config"].get("numeric_digest") != numeric_identity()
            or node["config"].get("numeric_threads") != db.settings.training_threads
        ):
            continue
        try:
            for ref in (
                node["evaluation"]["publication_anchor"],
                node["evaluation"]["scores"],
                node["dataset_artifact"],
            ):
                artifacts.read(ref)
        except (DomainError, OSError) as exc:
            failures.append({"version": version["id"], "error": getattr(exc, "code", type(exc).__name__)})
            continue
        return version, failures
    raise DomainError(
        "NO_VERIFIED_RETAINED_PARENT",
        json.dumps({"reason": "Never substitute a pruned child or frequency baseline", "failures": failures}),
    )


def seal(db, artifacts, target, clock):
    from .forecast import assess
    from .research_compute import predict_anchor
    from .scores import decode

    existing = db.rows("SELECT payload FROM parent_fallback_seals WHERE issue=%s", (target["issue"],))
    if existing:
        return existing[0]["payload"]
    started = clock()
    if not target["prepare_time"] <= started.astimezone(ZONE) < target["deadline_time"]:
        raise DomainError("PARENT_SEAL_WINDOW", "Seal only after17:00 before the outage deadline")
    version, failures = resolve(db, artifacts, target)
    node = version["snapshot"]
    data = json.loads(artifacts.read(node["dataset_artifact"]))
    if any(
        timestamp(r["available_at"]) > target["prepare_time"]
        or (r.get("observed_at") and timestamp(r["observed_at"]) > target["prepare_time"])
        or timestamp(r["draw_at"]) >= target["draw_time"]
        for r in data["rows"]
    ):
        raise DomainError("PARENT_DATA_BOUNDARY", "Parent data exceeds the legal pre-draw cutoff")
    gate = assess(
        decode(artifacts.read(node["evaluation"]["scores"]))["rows"], node["protocol"], node["decision"], data
    )
    prediction = predict_anchor(artifacts.read(node["evaluation"]["publication_anchor"]), data["rows"])
    tickets = prediction["red_top100"]
    if (
        len(tickets) != 100
        or len({tuple(t) for t in tickets}) != 100
        or any(len(t) != 6 or len(set(t)) != 6 or not all(1 <= v <= 33 for v in t) for t in tickets)
        or not 1 <= prediction["blue_top1"] <= 16
    ):
        raise DomainError("INVALID_PARENT_TOP100", "Require100 unique red combinations and one blue")
    reference = {
        "kind": "RETAINED_PARENT",
        "node": node["id"],
        "path": node["path"],
        "program": node["program_id"],
        "parent_version": version["id"],
        "completed_at": node["completed_at"],
        "spec": node["spec"],
        "anchor_sha256": node["evaluation"]["publication_anchor"]["sha256"],
        "publication_anchor": node["evaluation"]["publication_anchor"],
        "scores": node["evaluation"]["scores"],
        "dataset": node["dataset_artifact"],
        "dataset_id": node["dataset_id"],
        "validation": gate,
        "through_issue": node["through_issue"],
        "scope": "PARENT_FALLBACK_NOT_QUALIFIED",
        "qualified": False,
        "sealed_at": started.isoformat(),
        "cutoff": target["prepare_time"].isoformat(),
        "prediction_digest": digest(prediction),
        "skipped_unavailable_versions": failures,
        "red_probabilities": prediction["red_probabilities"],
        "blue_probabilities": prediction["blue_probabilities"],
    }
    payload = {
        "blue": prediction["blue_top1"],
        "tickets": tickets,
        "reference": reference,
        "parent_fallback": True,
        "lines": [
            f"剪枝回退来源：已接受父节点 {node['path']}；版本 {version['id']}；模型 {reference['anchor_sha256']}。",
            f"数据截至{node['through_issue']}，截止{reference['cutoff']}；正式资格未建立，父节点校验原因：{gate['reasons']}。",
            "以下Top100与唯一蓝球由该冻结父模型生成；回退预测单独结算，不计入正式合格推荐。",
        ],
    }
    with db.pool.connection() as c, c.transaction():
        c.execute("SELECT pg_advisory_xact_lock(740142)")
        if not target["prepare_time"] <= clock().astimezone(ZONE) < target["deadline_time"]:
            raise DomainError("PARENT_SEAL_WINDOW", "Generation must commit before the outage deadline")
        if c.execute(
            "SELECT 1 FROM jobs WHERE state='RUNNING' AND kind IN ('TRAIN','RESEARCH_EVALUATE','RESEARCH_PLAN') AND lease_until>now()"
        ).fetchone():
            raise DomainError(
                "WAITING_TRAINING_CHECKPOINT", "Wait for the live fit or planning operation to pause"
            )
        if c.execute("SELECT 1 FROM draws WHERE issue=%s", (target["issue"],)).fetchone():
            raise DomainError(
                "PARENT_RESULT_ALREADY_KNOWN", "Cannot create a new pre-draw seal after its result"
            )
        if c.execute(
            "SELECT 1 FROM effective_forecast_selections WHERE issue=%s AND state!='MISSED'",
            (target["issue"],),
        ).fetchone():
            raise DomainError("FORMAL_ALREADY_SEALED", "Do not replace a qualified prediction with fallback")
        c.execute(
            "INSERT INTO parent_fallback_seals(issue,version_id,payload) VALUES(%s,%s,%s) ON CONFLICT DO NOTHING",
            (target["issue"], version["id"], Jsonb(payload)),
        )
        return c.execute(
            "SELECT payload FROM parent_fallback_seals WHERE issue=%s", (target["issue"],)
        ).fetchone()["payload"]


def settle(db, issue):
    rows = db.rows(
        """SELECT f.payload,d.red,d.blue,p.source_id,p.first_verified_at
        FROM parent_fallback_seals f JOIN effective_draws d ON d.issue=f.issue
        JOIN official_publications p ON p.issue=d.issue WHERE f.issue=%s AND d.draw_at<=now()
        AND p.first_verified_at>=d.draw_at AND p.first_verified_at<=now()
        AND p.provenance='OFFICIAL_CWL_COMPLETE_LABEL_FIRST_VERIFIED_IN_NEXT'""",
        (issue,),
    )
    if not rows:
        raise DomainError("WAITING_PARENT_SETTLEMENT", "Complete official result required")
    row = rows[0]
    p = row["payload"]
    matches = [len(set(t) & set(row["red"])) for t in p["tickets"]]
    payload = {
        "prediction_digest": p["reference"]["prediction_digest"],
        "parent_version": p["reference"]["parent_version"],
        "source_id": row["source_id"],
        "red": row["red"],
        "blue": row["blue"],
        "blue_hit": int(p["blue"] == row["blue"]),
        "red_max_matches": max(matches),
        "red5_hit": int(max(matches) >= 5),
        "distribution": {str(i): matches.count(i) for i in range(7)},
        "scope": "PARENT_FALLBACK_SETTLEMENT_NOT_QUALIFIED_STATISTICS",
    }
    with db.pool.connection() as c:
        c.execute(
            "INSERT INTO parent_fallback_settlements(issue,payload) VALUES(%s,%s) ON CONFLICT DO NOTHING",
            (issue, Jsonb(payload)),
        )
        return c.execute(
            "SELECT payload FROM parent_fallback_settlements WHERE issue=%s", (issue,)
        ).fetchone()["payload"]
