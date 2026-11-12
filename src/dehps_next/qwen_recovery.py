"""Certified new-task recovery; failed semantic answers are never retried or repaired."""

from datetime import timedelta

from psycopg.types.json import Jsonb

from .domain import digest, now
from .errors import DomainError
from .research_output_guard import identity
from .training_window import status

STUDY = "qwen-output-recovery-20261112-v1"
RECOVERABLE = ("LOCAL_MODEL_TRUNCATED", "LOCAL_MODEL_REPETITION",
               "INVALID_LOCAL_REPLY", "INVALID_COMPARATIVE_SELECTION")
COOLDOWN_SECONDS = 1800


def context_identity(context):
    """Renaming/reordering IDs alone does not turn a failed case into a new task."""
    return digest({
        "parent": context["parent"],
        "candidates": sorted(digest(r["spec"]) for r in context["candidates"]),
        "evidence": sorted(digest({k: v for k, v in r.items() if k != "key"})
                           for r in context["evidence"]),
        "comparable_trials": context.get("comparable_trials"),
    })


def certificate(db, profile):
    rows = db.rows("""SELECT s.protocol,s.sha256,r.payload FROM research_review_studies s
        JOIN research_review_results r ON r.study_id=s.id WHERE s.id=%s""", (STUDY,))
    if not rows:
        return None
    row = rows[0]
    p, result = row["protocol"], row["payload"]
    if (digest(p) != row["sha256"] or p.get("guard_identity") != identity()
            or p.get("profile_id") != profile or not result.get("passed")
            or result.get("protocol_sha256") != row["sha256"]
            or result.get("previous_valid_rejected") != 0
            or result.get("source_slots") != 144 or not result.get("original_failure_detected")):
        return None
    return row


def arm(db, campaign, job, *, at=None):
    """Leave the error latched; grant a future qualified, genuinely new task one probe."""
    state = db.rows("SELECT * FROM qwen_selection_state WHERE id=1")[0]
    if state["reason"] not in RECOVERABLE or state["retry_after"] is not None:
        return
    certified = certificate(db, state["profile_id"])
    if not certified:
        return
    failures = db.rows("""SELECT id,call_id,payload,created_at FROM qwen_selection_audits
        WHERE created_at>=%s AND created_at<=%s AND source='FEEDBACK_VALUE_FALLBACK'
        AND payload->>'profile_id'=%s AND payload->>'reason'=%s
        AND jsonb_typeof(payload->'attempted_qwen_context')='object'
        AND jsonb_typeof(payload->'failed_qwen_call')='object'
        ORDER BY created_at LIMIT 1""",
        (state["updated_at"] - timedelta(seconds=5), state["updated_at"] + timedelta(minutes=5),
         state["profile_id"], state["reason"]))
    if not failures:
        return
    failed = failures[0]
    native = failed["payload"]["failed_qwen_call"]
    if native["state"] != "FAILED" or native["id"] != failed["call_id"]:
        return
    retry = max(failed["created_at"], state["last_scheduled_at"] or failed["created_at"])
    retry += timedelta(seconds=COOLDOWN_SECONDS)
    payload = {"phase": "ARMED_NEW_TASK_ONLY", "profile_id": state["profile_id"],
               "failed_audit": failed["id"], "failed_call": native["id"],
               "failed_context": context_identity(failed["payload"]["attempted_qwen_context"]),
               "certificate": certified["sha256"], "retry_after": retry.isoformat(),
               "cadence_and_fresh_feedback_required": True}
    with db.pool.connection() as c, c.transaction():
        db.fence(c, job)
        if status(c, at)["paused"]:
            return
        locked = c.execute("SELECT * FROM qwen_selection_state WHERE id=1 FOR UPDATE").fetchone()
        if any(locked[k] != state[k] for k in ("profile_id", "reason", "updated_at", "retry_after")):
            return
        c.execute("UPDATE qwen_selection_state SET retry_after=%s WHERE id=1", (retry,))
        c.execute("INSERT INTO qwen_selection_audits(campaign_id,call_id,source,payload) VALUES(%s,%s,'QWEN_RECOVERY',%s)",
                  (campaign["id"], native["id"], Jsonb(payload)))


def new_context_required(db, state, context):
    if state["reason"] not in RECOVERABLE:
        return False
    if not certificate(db, state["profile_id"]):
        return True
    rows = db.rows("""SELECT payload FROM qwen_selection_audits WHERE source='QWEN_RECOVERY'
        AND payload->>'profile_id'=%s AND payload->>'phase'='ARMED_NEW_TASK_ONLY'
        ORDER BY id DESC LIMIT 1""", (state["profile_id"],))
    return not rows or rows[0]["payload"]["failed_context"] == context_identity(context)


def recovered(c, campaign, profile, call, audit):
    # Called only after actual selection, strict parsing and feedback receipts pass.
    state = c.execute("SELECT * FROM qwen_selection_state WHERE id=1 FOR UPDATE").fetchone()
    if state["profile_id"] != profile or state["reason"] not in RECOVERABLE:
        return
    actual = c.execute("""SELECT m.state,m.metrics,m.created_at,m.model_digest,
        a.source,a.payload,a.created_at AS audit_created_at FROM research_model_calls m
        JOIN qwen_selection_audits a ON a.call_id=m.id WHERE m.id=%s AND a.id=%s""",
        (call, audit)).fetchone()
    if (not actual or actual["state"] != "SUCCEEDED" or actual["source"] != "QWEN_COMPARATIVE"
            or actual["payload"].get("profile_id") != profile
            or digest(actual["metrics"].get("selection_profile")) != profile
            or state["retry_after"] is None or actual["created_at"] < state["retry_after"]
            or actual["created_at"] <= state["updated_at"]
            or actual["audit_created_at"] < actual["created_at"]
            or actual["model_digest"] != actual["metrics"]["selection_profile"]["model_digest"]):
        raise DomainError("QWEN_RECOVERY_RECEIPT_REQUIRED", "A failed or fallback call cannot clear recovery")
    from .research_short_thinking import validate_receipt

    validate_receipt(actual["metrics"], actual["metrics"]["selection_profile"])
    prefix = c.execute("SELECT state,job_id,attempt_id FROM research_model_calls WHERE id=%s",
                       (actual["metrics"]["thinking_call_id"],)).fetchone()
    final = c.execute("SELECT job_id,attempt_id FROM research_model_calls WHERE id=%s", (call,)).fetchone()
    if not prefix or prefix["state"] != "SUCCEEDED" or any(prefix[k] != final[k] for k in final):
        raise DomainError("QWEN_RECOVERY_RECEIPT_REQUIRED", "Require the same-task successful thinking receipt")
    row = c.execute("""UPDATE qwen_selection_state SET reason=NULL,retry_after=NULL,updated_at=now()
        WHERE id=1 AND profile_id=%s AND reason=ANY(%s) RETURNING profile_id""",
        (profile, list(RECOVERABLE))).fetchone()
    if row:
        c.execute("INSERT INTO qwen_selection_audits(campaign_id,call_id,source,payload) VALUES(%s,%s,'QWEN_RECOVERY',%s)",
                  (campaign["id"], call, Jsonb({"phase": "RECOVERED_BY_ACTUAL_SELECTION",
                   "profile_id": profile, "successful_audit": audit, "at": now().isoformat()})))


def report_line(db):
    """Token totals alone do not establish that reasoning participates in training."""
    from .calendar import ZONE

    state = db.rows("SELECT * FROM qwen_selection_state WHERE id=1")[0]
    last = db.rows("""SELECT created_at FROM qwen_selection_audits
        WHERE source='QWEN_COMPARATIVE' AND payload->>'profile_id'=%s
        ORDER BY id DESC LIMIT 1""", (state["profile_id"],))
    with db.pool.connection() as c:
        paused = status(c)["paused"]
    activity = "开奖暂停，等待完整官方结果验证" if paused else "训练窗口开放"
    if state["reason"]:
        condition = f"受保护停用（{state['reason']}），候选选择使用反馈价值兜底"
    elif state["profile_id"]:
        condition = "合格配置已启用，按新反馈和时间间隔请求建议"
    else:
        condition = "尚无合格配置，候选选择使用兜底"
    previous = last[0]["created_at"].astimezone(ZONE).strftime("%Y-%m-%d %H:%M") if last else "无记录"
    return f"Qwen联动：{condition}；上次实际选择成功：{previous}（上海时间）；{activity}。"
