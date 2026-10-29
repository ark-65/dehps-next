"""Immutable report payloads and recipient-scoped SMTP outbox with uncertainty preserved."""

import hashlib
import html
import os
import smtplib
import ssl
import uuid
from email.message import EmailMessage
from email.utils import format_datetime, getaddresses

from psycopg.types.json import Jsonb

from .domain import digest, now, timestamp
from .errors import DomainError


def recipients():
    result = [address for _, address in getaddresses([os.getenv("DEHPS_NEXT_MAIL_TO", "")])]
    if not result or any("@" not in address or "\n" in address or "\r" in address for address in result):
        raise DomainError(
            "MAIL_CONFIGURATION", "Configure existing intended recipients in Next-only mail env"
        )
    return sorted(set(result))


class Mail:
    def __init__(self, db):
        self.db = db

    def queue(self, kind, issue, payload, evidence, cycle_id=None):
        if kind in ("PRE", "PRE_FINAL", "POST"):
            from .local_usage import report_line

            payload = {**payload, "lines": [*payload["lines"], report_line(self.db)]}
        identity = digest([kind, issue])
        with self.db.pool.connection() as c, c.transaction():
            c.execute(
                "INSERT INTO mail_reports(id,kind,issue,cycle_id,evidence,payload,digest) VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(kind,issue) DO NOTHING",
                (identity, kind, issue, cycle_id, evidence, Jsonb(payload), digest(payload)),
            )
            for address in recipients():
                hashed = hashlib.sha256(address.encode()).hexdigest()
                delivery = digest([identity, hashed])
                c.execute(
                    "INSERT INTO mail_deliveries(id,report_id,recipient_hash,message_id) VALUES(%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (delivery, identity, hashed, f"<{delivery}@dehps-next.local>"),
                )
        return identity

    @staticmethod
    def render(report):
        p = report["payload"]
        lines = [p["title"], "", *p["lines"]]
        if p.get("tickets"):
            lines.extend(["", "红球 Top100 / 唯一蓝球 Top1"])
            lines.extend(
                f"{i:03d}. {' '.join(f'{v:02d}' for v in red)} + {p['blue']:02d}"
                for i, red in enumerate(p["tickets"], 1)
            )
        text = "\n".join(lines)
        body = "<html><body style='font:16px/1.7 sans-serif;max-width:860px;margin:24px auto;color:#17202a'>"
        body += f"<h2>{html.escape(p['title'])}</h2>" + "".join(
            f"<p>{html.escape(line)}</p>" for line in p["lines"]
        )
        if p.get("tickets"):
            body += "<h3>红球 Top100 · 唯一蓝球 Top1</h3><table cellpadding='7' style='border-collapse:collapse;width:100%'><tr><th>序号</th><th>红球</th><th>蓝球</th></tr>"
            for i, red in enumerate(p["tickets"], 1):
                body += f"<tr style='border-top:1px solid #ddd'><td>{i:03d}</td><td style='color:#b91c1c'>{' · '.join(f'{v:02d}' for v in red)}</td><td style='color:#1d4ed8'>{p['blue']:02d}</td></tr>"
            body += "</table>"
        return text, body + "</body></html>"

    def deliver_one(self):
        with self.db.pool.connection() as c, c.transaction():
            c.execute(
                "UPDATE mail_attempts SET state='UNKNOWN',code='PROCESS_LOST_AFTER_SEND_CLAIM',ended_at=now() WHERE id IN (SELECT token FROM mail_deliveries WHERE state='SENDING' AND lease_until<now())"
            )
            c.execute(
                "UPDATE mail_deliveries SET state='UNKNOWN',last_error='PROCESS_LOST_AFTER_SEND_CLAIM' WHERE state='SENDING' AND lease_until<now()"
            )
            row = c.execute(
                "SELECT * FROM mail_deliveries WHERE state='READY' AND not_before<=now() ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1"
            ).fetchone()
            if not row:
                return None
            report = c.execute("SELECT * FROM mail_reports WHERE id=%s", (row["report_id"],)).fetchone()
            if report["kind"] in ("PRE", "PRE_FINAL") and now() >= timestamp(
                report["payload"]["send_deadline_utc"]
            ):
                c.execute(
                    "UPDATE mail_deliveries SET state='EXPIRED',last_error='PRE_DRAW_DEADLINE_PASSED' WHERE id=%s",
                    (row["id"],),
                )
                return {"state": "EXPIRED", "report": report["id"]}
            token = str(uuid.uuid4())
            c.execute(
                "UPDATE mail_deliveries SET state='SENDING',token=%s,attempts=attempts+1,lease_until=now()+interval '120 seconds' WHERE id=%s",
                (token, row["id"]),
            )
            c.execute(
                "INSERT INTO mail_attempts(id,delivery_id,state) VALUES(%s,%s,'SENDING')", (token, row["id"])
            )
        stage = "CONNECT"
        state, code = "UNKNOWN", "SMTP_UNCERTAIN"
        try:
            address = next(
                (r for r in recipients() if hashlib.sha256(r.encode()).hexdigest() == row["recipient_hash"]),
                None,
            )
            if address is None:
                raise DomainError("RECIPIENT_CHANGED", "Do not redirect a queued report")
            host = os.getenv("DEHPS_NEXT_SMTP_HOST", "smtp.qq.com")
            port = int(os.getenv("DEHPS_NEXT_SMTP_PORT", "465"))
            user = os.environ["DEHPS_NEXT_SMTP_USER"]
            password = os.environ["DEHPS_NEXT_SMTP_PASSWORD"]
            message = EmailMessage()
            message["Subject"] = report["payload"]["title"]
            message["From"] = user
            message["To"] = address
            message["Message-ID"] = row["message_id"]
            message["Date"] = format_datetime(now())
            plain, rich = self.render(report)
            message.set_content(plain)
            message.add_alternative(rich, subtype="html")
            with smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context()) as client:
                client.login(user, password)
                stage = "DATA"
                rejected = client.send_message(message)
                if rejected:
                    raise DomainError("RECIPIENT_REJECTED", "SMTP rejected intended recipient")
                state, code = "SENT", "SMTP_ACCEPTED"
        except (smtplib.SMTPException, OSError, DomainError, KeyError, ValueError) as exc:
            # Once DATA may have reached the server, do not blindly resend after a lost reply.
            definite = isinstance(
                exc, (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused, smtplib.SMTPDataError)
            )
            state = (
                "SENT"
                if state == "SENT"
                else "READY"
                if (stage == "CONNECT" or definite) and row["attempts"] < 2
                else "FAILED"
                if definite or stage == "CONNECT"
                else "UNKNOWN"
            )
            code = exc.code if isinstance(exc, DomainError) else type(exc).__name__
        with self.db.pool.connection() as c, c.transaction():
            c.execute(
                "UPDATE mail_deliveries SET state=%s,last_error=%s,accepted_at=CASE WHEN %s='SENT' THEN now() ELSE NULL END,not_before=now()+interval '5 minutes',lease_until=NULL WHERE id=%s AND token=%s AND state='SENDING'",
                (state, code, state, row["id"], token),
            )
            c.execute(
                "UPDATE mail_attempts SET state=%s,code=%s,ended_at=now() WHERE id=%s", (state, code, token)
            )
        return {"state": state, "code": code, "report": report["id"]}
