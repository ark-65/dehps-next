"""Local-provider token receipts: observation only, never currency or a usage admission limit."""

from psycopg.types.json import Jsonb

from .domain import now
from .errors import DomainError
from .resources import ZONE


def counter(value):
    return value if type(value) is int and value >= 0 else None


def add(c, day, model, inputs, outputs, unknown):
    values = (model, inputs, outputs, unknown)
    c.execute(
        """INSERT INTO local_token_totals(model,input_tokens,output_tokens,unreported_calls) VALUES(%s,%s,%s,%s)
        ON CONFLICT(model) DO UPDATE SET input_tokens=local_token_totals.input_tokens+excluded.input_tokens,
        output_tokens=local_token_totals.output_tokens+excluded.output_tokens,
        unreported_calls=local_token_totals.unreported_calls+excluded.unreported_calls""",
        values,
    )
    c.execute(
        """INSERT INTO local_token_days(day,model,input_tokens,output_tokens,unreported_calls) VALUES(%s,%s,%s,%s,%s)
        ON CONFLICT(day,model) DO UPDATE SET input_tokens=local_token_days.input_tokens+excluded.input_tokens,
        output_tokens=local_token_days.output_tokens+excluded.output_tokens,
        unreported_calls=local_token_days.unreported_calls+excluded.unreported_calls""",
        (day, *values),
    )


def record(c, call, metrics):
    row = c.execute("SELECT * FROM research_model_calls WHERE id=%s FOR UPDATE", (call,)).fetchone()
    inputs = counter(metrics.get("prompt_eval_count"))
    outputs = counter(metrics.get("eval_count"))
    for actual, known in ((inputs, row["usage_input_tokens"]), (outputs, row["usage_output_tokens"])):
        if actual is not None and known is not None and actual != known:
            raise DomainError(
                "TOKEN_RECEIPT_CONFLICT", "A known provider token count cannot be silently changed"
            )
    if inputs is None:
        inputs = row["usage_input_tokens"]
    if outputs is None:
        outputs = row["usage_output_tokens"]
    was_unknown = int(
        row["usage_recorded"] and (row["usage_input_tokens"] is None or row["usage_output_tokens"] is None)
    )
    is_unknown = int(inputs is None or outputs is None)
    add(
        c,
        row["created_at"].astimezone(ZONE).date(),
        row["model"],
        (inputs or 0) - (row["usage_input_tokens"] or 0),
        (outputs or 0) - (row["usage_output_tokens"] or 0),
        is_unknown - was_unknown,
    )
    c.execute(
        "UPDATE research_model_calls SET usage_recorded=true,usage_input_tokens=%s,usage_output_tokens=%s WHERE id=%s",
        (inputs, outputs, call),
    )


def reconcile(c):
    rows = c.execute("""SELECT mc.* FROM research_model_calls mc WHERE NOT usage_recorded
        AND (mc.state IN ('SUCCEEDED','FAILED','UNKNOWN') OR NOT EXISTS(
            SELECT 1 FROM jobs j WHERE j.id=mc.job_id AND j.token=mc.attempt_id AND j.state='RUNNING' AND j.lease_until>now()))
        ORDER BY mc.id LIMIT 128 FOR UPDATE""").fetchall()
    for row in rows:
        if row["state"] == "RESERVED":
            c.execute("UPDATE research_model_calls SET state='UNKNOWN' WHERE id=%s", (row["id"],))
        record(c, row["id"], row["metrics"] or {})


def import_receipt(c, identity, model, created_at, inputs, outputs, source):
    row = c.execute(
        """INSERT INTO local_token_imports(id,model,input_tokens,output_tokens,source,observed_at)
        VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING id""",
        (identity, model, counter(inputs), counter(outputs), Jsonb(source), created_at),
    ).fetchone()
    if row:
        add(
            c,
            created_at.astimezone(ZONE).date(),
            model,
            counter(inputs) or 0,
            counter(outputs) or 0,
            int(counter(inputs) is None or counter(outputs) is None),
        )


def summary(db):
    today = now().astimezone(ZONE).date()
    day = db.rows(
        "SELECT coalesce(sum(input_tokens),0)::bigint AS input_tokens,coalesce(sum(output_tokens),0)::bigint AS output_tokens,coalesce(sum(unreported_calls),0)::bigint AS unreported_calls FROM local_token_days WHERE day=%s",
        (today,),
    )[0]
    total = db.rows(
        "SELECT coalesce(sum(input_tokens),0)::bigint AS input_tokens,coalesce(sum(output_tokens),0)::bigint AS output_tokens,coalesce(sum(unreported_calls),0)::bigint AS unreported_calls FROM local_token_totals"
    )[0]
    for row in (day, total):
        row["total_tokens"] = row["input_tokens"] + row["output_tokens"]
    return {
        "mode": "LOCAL_TOKEN_OBSERVATION_ONLY",
        "billing": False,
        "usage_limits": False,
        "date": today.isoformat(),
        "today": day,
        "total": total,
        "coverage": "NEXT_RECORDED_PROVIDER_RECEIPTS;UNKNOWN_NOT_ESTIMATED",
    }


def report_line(db):
    usage = summary(db)
    d = usage["today"]
    t = usage["total"]
    line = f"本机Qwen token：今日输入{d['input_tokens']}、输出{d['output_tokens']}；已记录累计{t['total_tokens']}。本地推理，无外部API计费、无用量额度截停。"
    if t["unreported_calls"]:
        line += f"另有{t['unreported_calls']}次调用未返回完整token计数，未估算补齐。"
    return line
