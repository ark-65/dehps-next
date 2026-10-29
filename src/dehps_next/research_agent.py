"""Local structured inference -> actual math tools -> feedback-informed branch selection."""

import json
import os
import time
import urllib.error
import urllib.request

from psycopg.types.json import Jsonb

from .domain import canonical
from .errors import DomainError
from .research_compute import validate_spec
from .research_math import run_tool
from .research_policy import train_policy


def endpoint():
    url = os.getenv("DEHPS_NEXT_RESEARCH_URL", "")
    if url not in ("http://next-inference:11434", "http://127.0.0.1:11435"):
        raise DomainError(
            "LOCAL_INFERENCE_CONFIGURATION", "Configure the accepted Next-local inference endpoint"
        )
    return url


def request_json(path, payload=None, timeout=60):
    request = urllib.request.Request(
        endpoint() + path,
        data=canonical(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read(128 * 1024 + 1)
        if len(data) > 128 * 1024:
            raise DomainError("LOCAL_INFERENCE_RESPONSE_LIMIT", "Inference exceeded response budget")
        return json.loads(data)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise DomainError(
            "LOCAL_INFERENCE_UNAVAILABLE", "Local model request failed; no scripted fallback"
        ) from exc


def infer(db, artifacts, campaign, job, stage, context, schema, pulse):
    model = os.getenv("DEHPS_NEXT_RESEARCH_MODEL", "qwen3:1.7b")
    inventory = request_json("/api/tags", timeout=15)
    installed = next((m for m in inventory["models"] if m["name"] == model), None)
    if not installed:
        raise DomainError("LOCAL_MODEL_MISSING", "Selected local model is not installed")
    payload = {
        "model": model,
        "stream": False,
        "think": False,
        "keep_alive": "2m",
        "format": schema,
        "options": {"temperature": 0, "seed": 1729, "num_ctx": 4096, "num_predict": 800, "num_thread": 4},
        "messages": [
            {
                "role": "system",
                "content": "You are a bounded mathematics research agent. Reply in English JSON only. Use evidence, state falsifiable hypotheses, never claim lottery predictability. You cannot change scoring, budgets, data or execute code. Prior failures must influence your next direction. /no_think",
            },
            {"role": "user", "content": canonical(context)},
        ],
    }
    request_ref = artifacts.write(canonical(payload).encode(), category="research/inference")
    with db.pool.connection() as c, c.transaction():
        db.fence(c, job)
        c.execute("SELECT id FROM research_campaigns WHERE id=%s FOR UPDATE", (campaign["id"],))
        used = c.execute(
            "SELECT count(*) AS n FROM research_model_calls WHERE campaign_id=%s", (campaign["id"],)
        ).fetchone()["n"]
        if used >= campaign["config"]["max_model_calls"]:
            raise DomainError(
                "LOCAL_MODEL_CALL_BUDGET", "Model-call budget exhausted, including failed attempts"
            )
        from .resources import Resources

        Resources(db).model_call(c)
        call = c.execute(
            """INSERT INTO research_model_calls(campaign_id,job_id,attempt_id,stage,model,model_digest,request)
            VALUES(%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (campaign["id"], job["id"], job["token"], stage, model, installed["digest"], Jsonb(request_ref)),
        ).fetchone()["id"]
    pulse()
    started = time.monotonic()
    try:
        response = request_json("/api/chat", payload)
        pulse()
        if not response.get("done") or response.get("done_reason") == "length":
            raise DomainError(
                "LOCAL_MODEL_TRUNCATED", "Local response did not complete within its token budget"
            )
        content = response["message"]["content"]
        parsed = json.loads(content)
        response_ref = artifacts.write(
            canonical({"content": content}).encode(), category="research/inference"
        )
        metrics = {
            k: response.get(k)
            for k in (
                "total_duration",
                "load_duration",
                "prompt_eval_count",
                "eval_count",
                "eval_duration",
                "done_reason",
            )
        }
        metrics["wall_seconds"] = round(time.monotonic() - started, 4)
        with db.pool.connection() as c, c.transaction():
            db.fence(c, job)
            c.execute(
                "UPDATE research_model_calls SET response=%s,metrics=%s,state='SUCCEEDED' WHERE id=%s",
                (Jsonb(response_ref), Jsonb(metrics), call),
            )
        return parsed, {
            "call_id": call,
            "model": model,
            "model_digest": installed["digest"],
            "metrics": metrics,
        }
    except Exception:
        # A lost lease cannot publish a decision; the reserved call still counts against budget.
        with db.pool.connection() as c:
            c.execute(
                "UPDATE research_model_calls SET state='FAILED' WHERE id=%s AND state='RESERVED'", (call,)
            )
        raise


def propose(campaign, nodes, pulse, db, artifacts, job):
    selected = next(n for n in nodes if n["id"] == campaign["selected_node"])
    attempted = {n["spec"]["method"] for n in nodes if n["parent_id"] is not None}
    methods = (campaign["config"].get("topic") or {}).get("methods", ["fft", "ridge", "newton"])
    allowed = [m for m in methods if m not in attempted] or methods
    from .research_memory import known_specs

    known = [{"spec": spec} for spec in known_specs(db, campaign["dataset_id"])]
    # Named method slots make diversity a grammar constraint, not a prose request.
    slots = {m: (m, [8, 16, 24, 32]) for m in allowed}
    if len(allowed) == 1:
        slots = {"short_window": (allowed[0], [8, 16]), "long_window": (allowed[0], [24, 32])}
    base = {
        "epochs": {"type": "integer", "enum": [12, 20, 28]},
        "learning_rate": {"type": "number", "enum": [0.0005, 0.001, 0.002, 0.005]},
        "weight_decay": {"type": "number", "enum": [0, 0.001, 0.01]},
        "hypothesis": {"type": "string", "minLength": 12, "maxLength": 400},
        "falsification": {"type": "string", "minLength": 12, "maxLength": 400},
    }
    contracts = {
        key: {**base, "window": {"type": "integer", "enum": windows}} for key, (_, windows) in slots.items()
    }
    schema = {
        "type": "object",
        "properties": {
            "analysis_of_feedback": {"type": "string", "maxLength": 600},
            "hypotheses": {
                "type": "object",
                "properties": {
                    key: {
                        "type": "object",
                        "properties": contract,
                        "required": list(contract),
                        "additionalProperties": False,
                    }
                    for key, contract in contracts.items()
                },
                "required": list(slots),
                "additionalProperties": False,
            },
        },
        "required": ["analysis_of_feedback", "hypotheses"],
        "additionalProperties": False,
    }
    feedback = [
        {
            "path": n["path"],
            "spec": n["spec"],
            "decision": n["decision"],
            "summary": n["evaluation"]["summary"] if n["evaluation"] else None,
        }
        for n in nodes[-6:]
    ]
    context = {
        "task": "Fill each named hypothesis slot with a distinct executable falsifiable explanation and recipe. Revise ideas using actual prior feedback. Use concise sentences.",
        "slot_methods": {key: method for key, (method, _) in slots.items()},
        "parent": selected["path"],
        "research_question": campaign["config"].get("topic"),
        "earlier_topic_feedback": db.rows(
            "SELECT r.topic,n.spec,n.decision,n.evaluation->'summary' AS summary FROM research_nodes n JOIN research_campaigns r ON r.id=n.campaign_id WHERE r.id!=%s AND n.parent_id IS NOT NULL AND n.evaluation IS NOT NULL ORDER BY n.completed_at DESC LIMIT 4",
            (campaign["id"],),
        ),
        "excluded_recipes": [r["spec"] for r in known[-16:]],
        "feedback": feedback,
        "method_cards": {
            "fft": "Causal-window low-pass rFFT retains bins 0..3. Lottery labels may have no stable periodicity.",
            "ridge": "Linear residual head on causal window means, ridge penalty10, blend0.25. Shrinkage may reduce variance or introduce bias.",
            "newton": "Damped Newton temperature on excluded prior calibration tail. May reduce overconfidence; temperature alone cannot change argmax.",
        },
        "policy": "Development replay only; same frozen recent/random origins; blue log loss plus red Brier constraint; Top1 50 percent unproven.",
    }
    proposed, proposal_call = infer(db, artifacts, campaign, job, "HYPOTHESES", context, schema, pulse)
    hypotheses = proposed.get("hypotheses", {})
    if not isinstance(hypotheses, dict) or set(hypotheses) != set(slots) or len(canonical(proposed)) > 12000:
        raise DomainError("INVALID_AGENT_HYPOTHESES", "Required bounded hypothesis slots missing")
    candidates = []
    for key, (method, _) in slots.items():
        hypothesis = hypotheses[key]
        contract = contracts[key]
        if set(hypothesis) != set(contract):
            raise DomainError("INVALID_AGENT_SPEC", "Unexpected candidate fields")
        for field, rule in contract.items():
            if "enum" in rule and hypothesis[field] not in rule["enum"]:
                raise DomainError("INVALID_AGENT_SPEC", "Parameter outside accepted range")
        if not all(
            isinstance(hypothesis[k], str) and 12 <= len(hypothesis[k]) <= 400
            for k in ("hypothesis", "falsification")
        ):
            raise DomainError("INVALID_AGENT_HYPOTHESES", "Missing bounded falsifiable reasoning")
        spec = {
            **selected["spec"],
            "method": method,
            **{k: hypothesis[k] for k in ("window", "epochs", "learning_rate", "weight_decay")},
        }
        validate_spec(spec)
        if any(n["spec"] == spec for n in known) or any(v["spec"] == spec for v in candidates):
            continue
        candidates.append(
            {
                "slot": key,
                "spec": spec,
                "hypothesis": hypothesis["hypothesis"],
                "falsification": hypothesis["falsification"],
                "tool_result": run_tool(method),
            }
        )
    if not candidates:
        raise DomainError("SEARCH_SPACE_EXHAUSTED", "No novel recipe for this frozen snapshot")
    value, policy = train_policy(db, artifacts, campaign, job)
    for candidate in candidates:
        candidate["estimated_development_reward"] = value(
            candidate["spec"], selected["evaluation"]["summary"]
        )
    selection_schema = {
        "type": "object",
        "properties": {
            "selected": {"type": "integer", "enum": list(range(len(candidates)))},
            "reason": {"type": "string", "minLength": 12, "maxLength": 600},
            "next_if_failed": {"type": "string", "minLength": 12, "maxLength": 400},
        },
        "required": ["selected", "reason", "next_if_failed"],
        "additionalProperties": False,
    }
    selection, selection_call = infer(
        db,
        artifacts,
        campaign,
        job,
        "TOOL_FEEDBACK_SELECTION",
        {
            "task": "Select a candidate index using actual tool results, prior failures and uncertain value estimates. Explain limitations and the next direction if it fails.",
            "prior_analysis": proposed["analysis_of_feedback"],
            "prior_feedback": feedback,
            "candidates": candidates,
            "value_model_evidence": policy,
            "warning": "Toy numerical checks and tiny policy-training samples do not prove lottery performance.",
        },
        selection_schema,
        pulse,
    )
    if (
        set(selection) != {"selected", "reason", "next_if_failed"}
        or type(selection["selected"]) is not int
        or not 0 <= selection["selected"] < len(candidates)
    ):
        raise DomainError("INVALID_AGENT_SELECTION", "Select one bounded proposal")
    chosen = candidates[selection["selected"]]
    return {
        "source": "LOCAL_MODEL_WITH_MATH_TOOLS",
        "spec": chosen["spec"],
        "hypothesis": chosen["hypothesis"],
        "falsification": chosen["falsification"],
        "analysis_of_feedback": proposed["analysis_of_feedback"],
        "candidates": candidates,
        "selection": selection,
        "inference": [proposal_call, selection_call],
        "direction_value_model": policy,
    }


def use_local_model(db, campaign, nodes):
    """Reason at root and after three more observations; never stall compute on call allowance."""
    from .domain import now
    from .resources import ZONE, Resources

    if db.rows(
        "SELECT 1 FROM research_model_calls WHERE state='FAILED' AND created_at>now()-interval '5 minutes' LIMIT 1"
    ):
        return False
    used = db.rows("SELECT count(*) AS n FROM research_model_calls WHERE campaign_id=%s", (campaign["id"],))[
        0
    ]["n"]
    today = db.rows("SELECT calls FROM resource_days WHERE day=%s", (now().astimezone(ZONE).date(),))
    with db.pool.connection() as c:
        allowance = Resources.policy(c)["calls"]
    return (
        (len(nodes) == 1 or len(nodes) % 3 == 1)
        and used + 2 <= campaign["config"]["max_model_calls"]
        and (today[0]["calls"] if today else 0) + 2 <= allowance
    )
