"""Bounded Qwen thinking prefix, then a separately receipted structured answer."""

import hashlib
import math
import time

from psycopg.types.json import Jsonb

from .domain import canonical
from .errors import DomainError

CONTRACT = "comparative-v4.6-grounded-short"
CONTRACTS = ("comparative-v4.5-short", CONTRACT)
ASSESSMENT_CONTRACT = "candidate-keyed-copy-observations-v1"
TRANSPORT = "qwen-two-stage-budget-v1"
THINKING_TOKENS = 512
ANSWER_TOKENS = 1024
CONTEXT_TOKENS = 16384
CADENCE = {"min_interval_seconds": 1800, "min_new_feedback": 20}
PERFORMANCE_GATE = {"mean_seconds_max": 240, "p95_seconds_max": 300}


def profile(model_digest):
    return {
        "selector_contract": CONTRACT, "transport": TRANSPORT, "ground_output_schema": True,
        "assessment_contract": ASSESSMENT_CONTRACT,
        "model": "qwen3:4b", "model_digest": model_digest, "think": True,
        "thinking_budget_tokens": THINKING_TOKENS, "cadence": CADENCE,
        "raw_prompt_template": "qwen3-chatml-v1",
        "repetition_guard": "8_IDENTICAL_CONSECUTIVE_256_CHARACTER_BLOCKS",
        "backend": {
            "image": "sha256:b2f0122c476bc9fe7ce679d8bb4bd555351e25e2554eefb156f61cb0a89cf429",
            "engine": "Vulkan", "flash_attention": True, "kv_cache": "q8_0", "cpu_threads": 4,
        },
        "options": {"temperature": 0.6, "top_p": 0.95, "top_k": 20, "min_p": 0,
                    "seed": 1729, "num_ctx": CONTEXT_TOKENS, "num_predict": ANSWER_TOKENS},
    }


def validate_profile(profile):
    if (
        profile.get("selector_contract") not in CONTRACTS
        or (profile.get("selector_contract") == CONTRACT
            and profile.get("assessment_contract") != ASSESSMENT_CONTRACT)
        or profile.get("transport") != TRANSPORT
        or profile.get("model") != "qwen3:4b"
        or profile.get("think") is not True
        or profile.get("thinking_budget_tokens") != THINKING_TOKENS
        or profile.get("options", {}).get("num_predict") != ANSWER_TOKENS
        or profile.get("options", {}).get("num_ctx") != CONTEXT_TOKENS
        or profile.get("cadence") != CADENCE
    ):
        raise DomainError("SHORT_PROFILE_CHANGED", "Use the exact separately frozen short-thinking profile")


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def render(messages):
    parts = []
    for message in messages:
        text = message["content"]
        if message["role"] not in ("system", "user") or any(
            marker in text for marker in ("<|im_start|>", "<|im_end|>")
        ):
            raise DomainError("SHORT_PROMPT_FRAMING", "Reject ambiguous raw ChatML framing")
        parts.append(f"<|im_start|>{message['role']}\n{text}<|im_end|>\n")
    return "".join(parts) + "<|im_start|>assistant\n<think>\n"


def offload(profile):
    from .research_agent import request_json

    loaded = next(
        (r for r in request_json("/api/ps", timeout=15).get("models", [])
         if r.get("digest") == profile["model_digest"]), {}
    )
    result = {k: loaded.get(k) for k in ("size", "size_vram", "context_length")}
    if (
        type(result["size"]) is not int or result["size"] <= 0
        or type(result["size_vram"]) is not int or result["size_vram"] < result["size"]
        or result["context_length"] != CONTEXT_TOKENS
    ):
        raise DomainError("LOCAL_GPU_OFFLOAD_REQUIRED", "Short thinking requires full GPU and frozen context")
    return result


def generate(db, artifacts, campaign, job, call, payload, logical_request, progress, pulse, profile):
    from .local_usage import record
    from .research_stream import chat

    validate_profile(profile)
    prefix = render(payload["messages"])
    first = {
        "model": payload["model"], "raw": True, "think": False, "stream": True,
        "prompt": prefix, "keep_alive": "2m",
        "options": {**payload["options"], "num_predict": THINKING_TOKENS},
    }
    request = artifacts.write(canonical(first).encode(), category="research/inference")
    with db.pool.connection() as c, c.transaction():
        db.fence(c, job)
        child = c.execute(
            """INSERT INTO research_model_calls(campaign_id,job_id,attempt_id,stage,model,model_digest,request)
            VALUES(%s,%s,%s,'SHORT_THINKING_PREFIX',%s,%s,%s) RETURNING id""",
            (campaign["id"], job["id"], job["token"], profile["model"], profile["model_digest"], Jsonb(request)),
        ).fetchone()["id"]
    started = time.monotonic()
    partial = {}
    metrics = None

    def thinking_progress(value):
        nonlocal partial
        partial = {
            **value, "phase": "THINKING_PREFIX", "selection_profile": profile,
            "wall_seconds": round(time.monotonic() - started, 4),
        }
        with db.pool.connection() as c:
            c.execute("UPDATE research_model_calls SET metrics=%s WHERE id=%s", (Jsonb(partial), child))
        progress({"thinking_call_id": child, "logical_request": logical_request,
                  "phase": "THINKING_PREFIX", "phase_progress": partial,
                  "count_scope": "ANSWER_NOT_REQUESTED;THINK_COUNTS_IN_SEPARATE_PROVIDER_CALL"})

    try:
        response = chat(first, thinking_progress, pulse, job, path="/api/generate", raw=True)
        text = response["message"]["content"] + response["message"]["thinking"]
        metrics = {k: response.get(k) for k in (
            "total_duration", "load_duration", "prompt_eval_count", "eval_count", "eval_duration", "done_reason"
        )}
        metrics.update(
            phase="THINKING_PREFIX", selection_profile=profile, raw_thinking=text,
            wall_seconds=round(time.monotonic() - started, 4),
            count_scope="ACTUAL_PROVIDER_COUNTS;PREFIX_ONLY_NOT_A_SEMANTIC_SELECTION",
        )
        # A later GPU/lease rejection must not erase an already returned token receipt.
        with db.pool.connection() as c, c.transaction():
            c.execute("UPDATE research_model_calls SET metrics=%s WHERE id=%s", (Jsonb(metrics), child))
            record(c, child, metrics)
        metrics["offload"] = offload(profile)
        saved = artifacts.write(canonical({"thinking": text}).encode(), category="research/inference")
        with db.pool.connection() as c, c.transaction():
            db.fence(c, job)
            c.execute("UPDATE research_model_calls SET metrics=%s,response=%s,state='SUCCEEDED' WHERE id=%s",
                      (Jsonb(metrics), Jsonb(saved), child))
            record(c, child, metrics)
        from .research_output_guard import check

        check(text)
        if (
            type(metrics["eval_count"]) is not int or not 0 < metrics["eval_count"] <= THINKING_TOKENS
            or not metrics["prompt_eval_count"] or metrics["done_reason"] not in ("stop", "length")
        ):
            raise DomainError("SHORT_PROVIDER_RECEIPT", "Missing or excessive actual thinking token receipt")
    except Exception as exc:
        failure = {**(metrics or partial), "failure_code": getattr(exc, "code", type(exc).__name__)}
        with db.pool.connection() as c, c.transaction():
            c.execute("UPDATE research_model_calls SET metrics=metrics||%s,state='FAILED' WHERE id=%s",
                      (Jsonb(failure), child))
            current = c.execute("SELECT metrics FROM research_model_calls WHERE id=%s", (child,)).fetchone()
            record(c, child, current["metrics"])
        raise
    # This uniform, frozen transformation never inspects a selection's correctness.
    thought = text.split("</think>", 1)[0]
    if metrics["prompt_eval_count"] + len(thought.encode()) + ANSWER_TOKENS + 256 > CONTEXT_TOKENS:
        raise DomainError("MEMORY_CONTEXT_TOO_LARGE", "Never truncate facts or the actual thought prefix")
    second = {
        **first, "prompt": prefix + thought + "\n</think>\n\n", "format": payload["format"],
        "options": {**payload["options"], "num_predict": ANSWER_TOKENS},
    }
    second_ref = artifacts.write(canonical(second).encode(), category="research/inference")
    metadata = {
        "logical_request": logical_request, "thinking_call_id": child,
        "thinking_receipt": {"call_id": child, "model_digest": profile["model_digest"],
                             "metrics": metrics, "request": request, "response": saved},
        "short_thinking": {"transport": TRANSPORT, "thinking_budget_tokens": THINKING_TOKENS,
                           "answer_budget_tokens": ANSWER_TOKENS, "prefix_sha256": sha(prefix),
                           "actual_thought_prefix_sha256": sha(thought), "answer_prompt_sha256": sha(second["prompt"])},
        "raw_thinking": thought,
    }
    with db.pool.connection() as c, c.transaction():
        db.fence(c, job)
        c.execute("UPDATE research_model_calls SET request=%s,metrics=%s WHERE id=%s",
                  (Jsonb(second_ref), Jsonb(metadata), call))

    def answer_progress(value):
        progress({**value, **metadata,
                  "count_scope": "ANSWER_PROVIDER_COUNTS_PENDING;THINK_COUNTS_IN_SEPARATE_CALL"})

    response = chat(second, answer_progress, pulse, job, path="/api/generate", raw=True)
    response["short_metadata"] = metadata
    return response


def validate_receipt(metrics, profile):
    """Validate the two source-local provider receipts without treating the prefix as a choice."""
    validate_profile(profile)
    receipt = metrics.get("thinking_receipt", {})
    first = receipt.get("metrics", {})
    gpu = first.get("offload", {})
    short = metrics.get("short_thinking", {})
    if (
        receipt.get("model_digest") != profile["model_digest"]
        or first.get("selection_profile") != profile or first.get("phase") != "THINKING_PREFIX"
        or type(first.get("eval_count")) is not int or not 0 < first["eval_count"] <= THINKING_TOKENS
        or not first.get("prompt_eval_count") or first.get("done_reason") not in ("length", "stop")
        or not gpu.get("size") or type(gpu.get("size_vram")) is not int
        or gpu["size_vram"] < gpu["size"]
        or gpu.get("context_length") != CONTEXT_TOKENS
        or short.get("transport") != TRANSPORT
        or short.get("actual_thought_prefix_sha256") != sha(first.get("raw_thinking", "").split("</think>", 1)[0])
        or type(metrics.get("eval_count")) is not int or not 0 < metrics["eval_count"] <= ANSWER_TOKENS
        or metrics.get("done_reason") != "stop"
    ):
        raise DomainError("MECHANISM_NOT_VALIDATED", "Require both actual bounded full-GPU provider receipts")


def performance(db, study, profile):
    """Measure every semantic slot, including wrong answers; never count carried long replies."""
    rows = db.rows("SELECT arm,payload FROM research_review_selections WHERE study_id=%s ORDER BY pair,arm",
                   (study,))
    durations, calls, thoughts = [], set(), set()
    complete = len(rows) == 144
    for row in rows:
        record = row["payload"].get("actual_call")
        if not record or not record.get("actual_prefix_verified") or row["payload"].get("recovery_source"):
            complete = False
            continue
        m = record["metrics"]
        expected = {**profile, "options": {**profile["options"], "seed": int(row["arm"].split(":")[-1])}}
        first = m.get("thinking_receipt", {}).get("metrics", {})
        value = m.get("wall_seconds")
        if (
            record.get("model_digest") != profile["model_digest"] or m.get("selection_profile") != expected
            or first.get("selection_profile") != expected
            or type(first.get("eval_count")) is not int or not 0 < first["eval_count"] <= THINKING_TOKENS
            or type(m.get("eval_count")) is not int or not 0 < m["eval_count"] <= ANSWER_TOKENS
            or m.get("done_reason") not in ("stop", "length")
            or type(value) not in (float, int) or not math.isfinite(value) or value < 0
        ):
            complete = False
            continue
        calls.add(record["call_id"])
        thoughts.add(m["thinking_call_id"])
        durations.append(value)
    complete = complete and len(calls) == len(thoughts) == 144 and not calls.intersection(thoughts)
    mean = sum(durations) / len(durations) if durations else None
    p95 = sorted(durations)[math.ceil(len(durations) * 0.95) - 1] if durations else None
    return {
        "complete_actual_receipts": complete, "logical_requests": len(rows),
        "measured_requests": len(durations), "distinct_final_calls": len(calls),
        "distinct_thinking_calls": len(thoughts), "mean_seconds": mean, "p95_seconds": p95,
        "passed": bool(complete and mean <= PERFORMANCE_GATE["mean_seconds_max"]
                       and p95 <= PERFORMANCE_GATE["p95_seconds_max"]),
        "scope": "ACTUAL_TWO_PHASE_LOGICAL_LATENCY;WRONG_ANSWERS_INCLUDED;PHYSICAL_RETRIES_SEPARATE",
    }
