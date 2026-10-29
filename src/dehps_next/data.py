import json
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from psycopg.types.json import Jsonb

from .domain import canonical, digest, now, timestamp, validate_draw
from .errors import DomainError

CWL_URL = (
    "https://www.cwl.gov.cn/cwl_admin/front/cwlkj/search/kjxx/findDrawNotice"
    "?name=ssq&issueCount=100&pageNo=1&pageSize=100&systemType=PC"
)


def fetch_official():
    request = urllib.request.Request(
        CWL_URL, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.cwl.gov.cn/"}
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        if not response.geturl().startswith("https://www.cwl.gov.cn/"):
            raise DomainError("SOURCE_REDIRECT", "Unexpected official-source redirect")
        body = response.read(2 * 1024 * 1024 + 1)
    if len(body) > 2 * 1024 * 1024:
        raise DomainError("SOURCE_TOO_LARGE", "Official response exceeds 2MiB")
    try:
        payload = json.loads(body)
        records = []
        if payload.get("state") != 0 or not payload.get("result"):
            raise ValueError("Official feed did not return successful results")
        for row in payload["result"]:
            date = str(row["date"])[:10]
            day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=ZoneInfo("Asia/Shanghai"))
            records.append(
                validate_draw(
                    {
                        "issue": str(row["code"]),
                        "red": [int(v) for v in row["red"].split(",")],
                        "blue": int(row["blue"]),
                        "draw_at": day.isoformat(),
                        "available_at": day.replace(hour=23, minute=59, second=59).isoformat(),
                    }
                )
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise DomainError("SOURCE_FORMAT", "Official red/blue response format is invalid") from exc
    return records, body


class DataService:
    def __init__(self, db, artifacts):
        self.db, self.artifacts = db, artifacts

    def ingest(self, records, *, source_url, raw, provenance, observed_at=None):
        observed_at = observed_at or now()
        clean = [validate_draw(r) for r in records]
        if not clean or len(clean) > 5000:
            raise DomainError("INVALID_BATCH", "Expected 1..5000 draw records")
        if len({r["issue"] for r in clean}) != len(clean):
            raise DomainError("DUPLICATE_ISSUE", "Duplicate issue in input batch")
        if any(timestamp(r["draw_at"]) > observed_at for r in clean):
            raise DomainError("FUTURE_LABEL", "Future draw labels cannot be ingested")
        with self.db.pool.connection() as c, c.transaction():
            c.execute("SELECT pg_advisory_xact_lock(740132)")
            new = []
            for r in clean:
                old = c.execute("SELECT content_digest FROM draws WHERE issue=%s", (r["issue"],)).fetchone()
                if old:
                    if old["content_digest"] != digest(r):
                        raise DomainError("DATA_CONFLICT", f"Conflicting immutable issue {r['issue']}")
                else:
                    new.append(r)
            if not new:
                batch_id = digest([source_url, provenance, sorted(clean, key=lambda r: r["issue"])])
                receipt = c.execute(
                    "SELECT source_id FROM source_batches WHERE id=%s", (batch_id,)
                ).fetchone()
                if receipt:
                    return {
                        "inserted": 0,
                        "duplicate": len(clean),
                        "source": receipt["source_id"],
                        "semantic_receipt_reused": True,
                    }
                # Retain a compact independent source receipt even when all draws already exist.
                ref = self.artifacts.write(raw, category="sources")
                c.execute(
                    "INSERT INTO sources VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (ref["sha256"], source_url, observed_at, Jsonb(ref), provenance),
                )
                c.execute(
                    "INSERT INTO source_batches VALUES(%s,%s) ON CONFLICT DO NOTHING",
                    (batch_id, ref["sha256"]),
                )
                return {"inserted": 0, "duplicate": len(clean), "source": ref["sha256"]}
            ref = self.artifacts.write(raw, category="sources")
            source_id = ref["sha256"]
            c.execute(
                "INSERT INTO sources VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (source_id, source_url, observed_at, Jsonb(ref), provenance),
            )
            for r in new:
                c.execute(
                    """INSERT INTO draws(issue,draw_at,available_at,observed_at,red,blue,
                    source_id,content_digest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        r["issue"],
                        r["draw_at"],
                        r["available_at"],
                        observed_at,
                        r["red"],
                        r["blue"],
                        source_id,
                        digest(r),
                    ),
                )
            return {"inserted": len(new), "duplicate": len(clean) - len(new), "source": source_id}

    def sync(self):
        records, raw = fetch_official()
        return self.ingest(
            records,
            source_url=CWL_URL,
            raw=raw,
            provenance="OFFICIAL_CWL;DATE_ONLY;availability=end-of-day-conservative",
        )

    def snapshot(self, c, *, cutoff, target_draw_at, mode):
        query = """SELECT issue,red,blue,draw_at,available_at,observed_at,source_id FROM draws
                   WHERE available_at<=%s AND draw_at<%s"""
        params = [cutoff, target_draw_at]
        if mode == "FORWARD":
            query += " AND observed_at<=%s"
            params.append(cutoff)
        records = c.execute(query + " ORDER BY draw_at,issue", params).fetchall()
        rows = [
            {**r, **{k: r[k].isoformat() for k in ("draw_at", "available_at", "observed_at")}}
            for r in records
        ]
        if not rows:
            raise DomainError("NO_PRIOR_DATA", "No past-available training data")
        payload = {
            "mode": mode,
            "cutoff": cutoff.isoformat(),
            "target_draw_at": target_draw_at.isoformat(),
            "rows": rows,
            "availability_contract": "prior-available-only;replay-is-retrospective",
        }
        identity = digest(payload)
        existing = c.execute("SELECT * FROM datasets WHERE id=%s", (identity,)).fetchone()
        if existing:
            return existing
        ref = self.artifacts.write(canonical(payload).encode(), category="datasets")
        return c.execute(
            """INSERT INTO datasets(id,through_issue,cutoff,mode,sample_count,artifact)
            VALUES(%s,%s,%s,%s,%s,%s) RETURNING *""",
            (identity, rows[-1]["issue"], cutoff, mode, len(rows), Jsonb(ref)),
        ).fetchone()

    def research_snapshot(self, c):
        cutoff = c.execute(
            "SELECT max(available_at) AS cutoff FROM draws WHERE available_at<=now()"
        ).fetchone()["cutoff"]
        if cutoff is None:
            raise DomainError("NO_PRIOR_DATA", "No available history for research")
        return self.snapshot(c, cutoff=cutoff, target_draw_at=cutoff, mode="REPLAY")
