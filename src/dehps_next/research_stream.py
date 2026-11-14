"""Local NDJSON inference with observable progress, rather than a total request deadline."""

import hashlib
import http.client
import json
import time
import urllib.error
import urllib.request

from .domain import canonical
from .errors import DomainError


def provider_error_code(error):
    # This is a provider-observed generation failure, not an unperformed slot.
    if error == "prediction aborted, token repeat limit reached":
        return "LOCAL_MODEL_REPETITION"
    return "LOCAL_INFERENCE_UNAVAILABLE"


def chat(payload, progress, pulse, job, *, silence_seconds=180, path="/api/chat", raw=False):
    from .research_agent import endpoint

    request = urllib.request.Request(
        endpoint() + path,
        data=canonical(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    content, thinking = [], []
    chunks, total_bytes, saved_at = 0, 0, time.monotonic()
    provider_failure = {}
    pulsed_at = saved_at - 1
    job["local_stream_active"] = True
    job["local_stream_progress_at"] = saved_at

    def save():
        progress(
            {
                "raw_completion": "".join(content),
                "raw_thinking": "".join(thinking),
                "stream_chunks_observed": chunks,
                "stream_bytes_observed": total_bytes,
                "count_scope": "PROVIDER_COUNTS_PENDING;CHUNKS_ARE_NOT_TOKENS",
                **provider_failure,
            }
        )

    try:
        # The socket timeout applies only to a period without network progress.
        # Active generation has no cumulative wall deadline.
        with urllib.request.urlopen(request, timeout=silence_seconds) as response:
            while True:
                line = response.readline(128 * 1024 + 1)
                if not line:
                    raise DomainError("LOCAL_STREAM_INCOMPLETE", "Provider closed before its final receipt")
                if len(line) > 128 * 1024:
                    raise DomainError(
                        "LOCAL_INFERENCE_RESPONSE_LIMIT", "A provider frame exceeds the physical buffer"
                    )
                frame = json.loads(line)
                if frame.get("error"):
                    code = provider_error_code(frame["error"])
                    provider_failure = {
                        "provider_error_code": code,
                        "provider_error_frame_sha256": hashlib.sha256(canonical(frame).encode()).hexdigest(),
                    }
                    raise DomainError(
                        code, "Local streaming provider reported an error"
                    )
                message = frame if raw else frame.get("message", {})
                delta = message.get("response" if raw else "content", "")
                thought = message.get("thinking", "")
                if not isinstance(delta, str) or not isinstance(thought, str):
                    raise DomainError("INVALID_LOCAL_REPLY", "Streaming message fields must be text")
                content.append(delta)
                thinking.append(thought)
                chunks += 1
                from .research_output_guard import check, unsafe_text

                if unsafe_text(delta) or unsafe_text(thought):
                    provider_failure = {
                        "rejected_frame_sha256": hashlib.sha256(line).hexdigest(),
                        "rejected_frame_bytes": len(line),
                        "rejected_frame_raw": line,
                        "count_scope": "PRIOR_VALID_UTF8_TEXT_BYTES_ONLY;UNSAFE_FRAME_NOT_COUNTED_AS_TOKENS",
                    }
                    if frame.get("done"):
                        provider_failure.update({key: frame.get(key) for key in (
                            "total_duration", "load_duration", "prompt_eval_count", "eval_count",
                            "eval_duration", "done_reason",
                        )})
                    # The callbacks persist the original text as opaque evidence;
                    # reject it before either JSONB or UTF-8 encoding can lose it.
                    save()
                    check(delta if unsafe_text(delta) else thought)
                total_bytes += len(delta.encode()) + len(thought.encode())
                if total_bytes > 2 * 1024**2:
                    raise DomainError("LOCAL_INFERENCE_RESPONSE_LIMIT", "Preserve bounded local artifacts")
                if delta or thought:
                    job["local_stream_progress_at"] = time.monotonic()
                if time.monotonic() - pulsed_at >= 0.5 or frame.get("done"):
                    pulse()
                    pulsed_at = time.monotonic()
                if time.monotonic() - saved_at >= 5:
                    save()
                    saved_at = time.monotonic()
                # Reject a demonstrated generation loop, never a long coherent thought.
                tail = "".join(thinking if thought else content)[-2048:]
                if not frame.get("done"):
                    check(tail)
                if len(tail) == 2048 and tail[-256:] * 8 == tail:
                    raise DomainError(
                        "LOCAL_MODEL_REPETITION", "Eight identical consecutive256-character blocks"
                    )
                if frame.get("done"):
                    frame["message"] = {"content": "".join(content), "thinking": "".join(thinking)}
                    return frame
    except (OSError, http.client.HTTPException, json.JSONDecodeError) as exc:
        raise DomainError("LOCAL_INFERENCE_UNAVAILABLE", "Local stream stalled or became unreadable") from exc
    finally:
        job["local_stream_active"] = False
        save()
