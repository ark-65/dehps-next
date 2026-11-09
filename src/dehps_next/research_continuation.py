"""Use idle compute for distinct paired trials during an actual primary Qwen call."""

import json
import uuid

from .domain import digest
from .research_memory import untried_specs
from .research_search import novel_specs
from .resources import Resources, TERMINAL
from .training_window import status as training_window


def fill_gap(db, artifacts):
    calls = db.rows("""SELECT m.id AS source_call_id,coalesce(m.metrics->'logical_request',m.request) AS source_request,r.* FROM research_model_calls m
        JOIN research_campaigns r ON r.id=m.campaign_id
        JOIN jobs j ON j.id=m.job_id AND j.token=m.attempt_id
        WHERE m.state='RESERVED' AND m.stage LIKE 'CANDIDATE_SELECTION_V4_%%'
          AND j.state='RUNNING' AND j.lease_until>now()
          AND r.program_id='autonomous-v2' ORDER BY m.id DESC LIMIT 1""")
    if not calls or Resources(db).pressure():
        return None
    source = calls[0]
    if db.rows("""SELECT 1 FROM research_campaigns WHERE config ? 'inference_continuation'
        AND NOT (status=ANY(%s)) AND status NOT LIKE 'BLOCKED_%%' LIMIT 1""", (list(TERMINAL),)):
        return None
    call = {"id": source["source_call_id"], "request": source["source_request"]}
    request = json.loads(artifacts.read(call["request"]))
    context = json.loads(request["messages"][1]["content"])
    reserved = {digest(item["spec"]) for item in context["candidates"]}
    parent = db.rows("SELECT spec FROM research_nodes WHERE id=%s", (source["selected_node"],))
    if not parent:
        return None
    topic = source["config"]["topic"]
    offered = novel_specs(db, source["dataset_id"], source["config"]["code_digest"], topic)
    child = next((s for s in offered if digest(s) not in reserved), None)
    if child is None:
        return None
    from .research import Research

    with db.pool.connection() as c, c.transaction():
        if not c.execute("SELECT pg_try_advisory_xact_lock(740134) AS locked").fetchone()["locked"]:
            return None
        if training_window(c)["paused"]:
            return None
        if not c.execute("SELECT 1 FROM research_model_calls WHERE id=%s AND state='RESERVED'", (call["id"],)).fetchone():
            return None
        if c.execute("""SELECT 1 FROM research_campaigns
            WHERE config ? 'inference_continuation' AND NOT (status=ANY(%s))
              AND status NOT LIKE 'BLOCKED_%%' LIMIT 1""", (list(TERMINAL),)).fetchone():
            return None
        if c.execute("""SELECT 1 FROM jobs j LEFT JOIN research_nodes n ON n.id=j.research_node_id
            LEFT JOIN research_campaigns r ON r.id=n.campaign_id
            WHERE j.state IN ('READY','RUNNING') AND j.kind!='RESEARCH_PLAN'
              AND NOT coalesce(r.config ? 'inference_continuation',false) LIMIT 1""").fetchone():
            return None
        if not untried_specs(db, source["dataset_id"], [child], connection=c):
            return None
        frozen = {"primary_campaign": source["id"], "call_id": call["id"],
                  "dataset_id": source["dataset_id"], "protocol": source["protocol"],
                  "child": child, "reserved_qwen_recipes": sorted(reserved),
                  "scope": "PAIRED_DEVELOPMENT_ONLY;NO_PRIMARY_PARENT_OR_REPORT_PROMOTION"}
        name = "cpu-continuation-" + uuid.uuid4().hex[:24]
        Research(db, artifacts).create(name, planner="rules", max_nodes=2,
            root_spec=parent[0]["spec"], topic=topic, continuation=frozen, connection=c)
        return name


def plan(controller, job, context, pulse):
    db = controller.db
    frozen = context["config"]["inference_continuation"]
    pulse()
    with db.pool.connection() as c, c.transaction():
        db.fence(c, job)
        campaign = c.execute("SELECT * FROM research_campaigns WHERE id=%s FOR UPDATE",
                             (context["campaign_id"],)).fetchone()
        nodes = c.execute("SELECT id FROM research_nodes WHERE campaign_id=%s",
                          (campaign["id"],)).fetchall()
        if len(nodes) == 1 and untried_specs(db, context["dataset_id"], [frozen["child"]], connection=c):
            controller._node(c, campaign["id"], "1-1", campaign["selected_node"], frozen["child"],
                {"source": "INFERENCE_CPU_CONTINUATION", "primary_call": frozen["call_id"],
                 "hypothesis": "Registered feedback-neighbor trial while primary Qwen is pending",
                 "falsification": "Unchanged paired chronological red/blue100/50/10 gates"})
        else:
            c.execute("UPDATE research_campaigns SET status='BATCH_COMPLETE',updated_at=now() WHERE id=%s",
                      (campaign["id"],))
            controller.decision(c, campaign["id"], context["id"], "BATCH_COMPLETE",
                {"source": "INFERENCE_CPU_CONTINUATION", "nodes": len(nodes), "primary_call": frozen["call_id"]})
        db.complete(c, job)
