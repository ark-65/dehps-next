"""Import officially verified Super Lotto draw numbers into Next PostgreSQL."""

import argparse
import json
import re
import signal
import threading
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from time import sleep
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg_pool import PoolTimeout

from .config import Settings
from .db import Database

OFFICIAL_API = "https://webapi.sporttery.cn/gateway/lottery/getHistoryPageListV1.qry"
SHANGHAI = ZoneInfo("Asia/Shanghai")
FIRST_ISSUE = "07001"
ISSUE = re.compile(r"[0-9]{2}(?!000)[0-9]{3}")
PAGE_SIZE = 100
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class IngestError(Exception):
    pass


@dataclass(frozen=True)
class Draw:
    issue: str
    draw_date: date
    front: tuple[int, ...]
    back: tuple[int, ...]


@dataclass(frozen=True)
class Page:
    total: int
    pages: int
    draws: list[Draw]


def official_url(page=1, size=PAGE_SIZE, start=None, end=None):
    query = {"gameNo": 85, "provinceId": 0, "isVerify": 1, "pageNo": page, "pageSize": size}
    if start is not None:
        query.update(startTerm=start, endTerm=end)
    return f"{OFFICIAL_API}?{urlencode(query)}"


def parse_draw(row, today):
    if not isinstance(row, dict):
        raise IngestError("Official response contains a non-object draw")
    issue = row.get("lotteryDrawNum")
    if not isinstance(issue, str) or not ISSUE.fullmatch(issue) or issue < FIRST_ISSUE:
        raise IngestError("Official draw has an invalid issue")
    status = (row.get("lotteryGameNum"), row.get("verify"), row.get("lotteryDrawStatus"),
              row.get("lotterySuspendedFlag"))
    if status != ("85", 1, 20, 0):
        raise IngestError(f"Issue {issue} is not a verified Super Lotto draw")
    day = row.get("lotteryDrawTime")
    numbers = row.get("lotteryDrawResult")
    if not isinstance(day, str) or not re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}", day):
        raise IngestError(f"Issue {issue} has an invalid draw date")
    try:
        draw_date = date.fromisoformat(day)
    except ValueError as exc:
        raise IngestError(f"Issue {issue} has an invalid draw date") from exc
    if day[2:4] != issue[:2] or draw_date > today:
        raise IngestError(f"Issue {issue} has a mismatched or future draw date")
    if not isinstance(numbers, str) or not re.fullmatch(r"[0-9]{1,2}(?:\s+[0-9]{1,2}){6}", numbers):
        raise IngestError(f"Issue {issue} does not have seven draw numbers")
    digits = [int(number) for number in numbers.split()]
    front, back = tuple(sorted(digits[:5])), tuple(sorted(digits[5:]))
    if len(set(front)) != 5 or front[0] < 1 or front[-1] > 35:
        raise IngestError(f"Issue {issue} has invalid front numbers")
    if back[0] < 1 or back[0] >= back[1] or back[1] > 12:
        raise IngestError(f"Issue {issue} has invalid back numbers")
    return Draw(issue, draw_date, front, back)


def parse_page(payload, page, size, today):
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise IngestError("Official API did not return a successful page")
    value = payload.get("value")
    if not isinstance(value, dict) or value.get("pageNo") != page or value.get("pageSize") != size:
        raise IngestError("Official API returned different pagination parameters")
    total, pages, rows = value.get("total"), value.get("pages"), value.get("list")
    if not isinstance(total, int) or total < 0 or pages != (total + size - 1) // size:
        raise IngestError("Official API returned invalid pagination totals")
    if not isinstance(rows, list) or len(rows) != min(size, max(0, total - (page - 1) * size)):
        raise IngestError("Official API returned an incomplete page")
    return Page(total, pages, [parse_draw(row, today) for row in rows])


def fetch_page(page=1, size=PAGE_SIZE, start=None, end=None):
    url = official_url(page, size, start, end)
    request = Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.lottery.gov.cn/"})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=10) as response:
                if urlsplit(response.geturl())[:2] != ("https", "webapi.sporttery.cn"):
                    raise IngestError("Official API redirected outside the official endpoint")
                body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise IngestError("Official API response is too large")
            return parse_page(json.loads(body), page, size, datetime.now(SHANGHAI).date())
        except (OSError, ValueError, IngestError) as exc:
            if attempt == 2:
                reason = str(exc) if isinstance(exc, IngestError) else type(exc).__name__
                raise IngestError(f"Official page {page} for {start or 'latest'}–{end or 'latest'}: {reason}") from exc
            sleep(2 ** attempt)


def annual_ranges(start, end):
    for year in range(int(start[:2]), int(end[:2]) + 1):
        yield max(start, f"{year:02d}001"), min(end, f"{year:02d}999")


def fetch_draws(start, end):
    draws = []
    for lower, upper in annual_ranges(start, end):
        first = fetch_page(start=lower, end=upper)
        if not 1 <= first.total <= 999:
            raise IngestError(f"Unexpected official draw count in {lower}–{upper}")
        year_draws = first.draws.copy()
        for number in range(2, first.pages + 1):
            page = fetch_page(number, start=lower, end=upper)
            if (page.total, page.pages) != (first.total, first.pages):
                raise IngestError(f"Official pagination shifted in {lower}–{upper}")
            year_draws.extend(page.draws)
        if any(not lower <= draw.issue <= upper for draw in year_draws):
            raise IngestError(f"Official API returned an issue outside {lower}–{upper}")
        draws.extend(reversed(year_draws))

    if draws[0].issue != start or draws[-1].issue != end:
        raise IngestError(f"The official response does not cover both {start} and {end}")
    for before, after in zip(draws, draws[1:]):
        before_year, after_year = int(before.issue[:2]), int(after.issue[:2])
        if before_year == after_year:
            consecutive = int(after.issue[2:]) == int(before.issue[2:]) + 1
        else:
            consecutive = after_year == before_year + 1 and after.issue[2:] == "001"
        if not consecutive or before.draw_date >= after.draw_date:
            raise IngestError(f"Official issue sequence or date mismatch near {before.issue} and {after.issue}")
    return draws


def connect(dsn):
    return psycopg.connect(
        dsn, connect_timeout=10, autocommit=True, options="-c statement_timeout=15000 -c lock_timeout=3000"
    )


def store_draws(db, draws, observed_at, expected_total):
    start, end = draws[0].issue, draws[-1].issue
    with db.transaction():
        db.execute("SELECT pg_advisory_xact_lock(740185)")
        existing = {
            issue: (day, tuple(front), tuple(back))
            for issue, day, front, back in db.execute(
                "SELECT issue, draw_date, front, back FROM dlt_draws WHERE issue BETWEEN %s AND %s",
                (start, end),
            )
        }
        pending = []
        for draw in draws:
            current = existing.get(draw.issue)
            if current is None:
                pending.append((draw.issue, draw.draw_date, list(draw.front), list(draw.back),
                                official_url(size=1, start=draw.issue, end=draw.issue), observed_at))
            elif current != (draw.draw_date, draw.front, draw.back):
                raise IngestError(f"Official draw conflicts with stored issue {draw.issue}")
        with db.cursor() as cursor:
            cursor.executemany(
                "INSERT INTO dlt_draws (issue,draw_date,front,back,source_url,observed_at) VALUES (%s,%s,%s,%s,%s,%s)",
                pending,
            )
        if expected_total is not None:
            stored = db.execute("SELECT count(*) FROM dlt_draws WHERE issue <= %s", (end,)).fetchone()[0]
            if stored != expected_total:
                raise IngestError(f"Through {end}, expected {expected_total} official draws but found {stored}")
        latest_issue, latest_date = db.execute(
            "SELECT issue, draw_date FROM dlt_draws ORDER BY issue DESC LIMIT 1"
        ).fetchone()
    return {"inserted": len(pending), "duplicates": len(existing),
            "stored_latest_issue": latest_issue, "stored_latest_date": latest_date}


def ingest(dsn, mode, through=None):
    latest = fetch_page(size=1)
    if not latest.draws:
        raise IngestError("Official API returned no verified Super Lotto draws")
    head = latest.draws[0]
    end = through or head.issue
    if end > head.issue:
        raise IngestError(f"Requested issue {end} is later than the latest verified issue {head.issue}")
    start = FIRST_ISSUE
    if mode == "sync":
        with connect(dsn) as db:
            recent = db.execute("SELECT issue FROM dlt_draws ORDER BY issue DESC LIMIT 10").fetchall()
        if recent:
            if recent[0][0] > head.issue:
                raise IngestError(f"Official head {head.issue} precedes stored issue {recent[0][0]}")
            start = recent[-1][0]
    draws = fetch_draws(start, end)
    if end == head.issue and draws[-1] != head:
        raise IngestError(f"Official latest and history responses disagree for issue {head.issue}")
    with connect(dsn) as db:
        stored = store_draws(db, draws, datetime.now(SHANGHAI), latest.total if end == head.issue else None)
    return {"official_latest_issue": head.issue, "official_latest_date": head.draw_date,
            "official_total": latest.total, "start_issue": start, "end_issue": end, **stored}


def next_run(after, stored_date):
    day = after.date()
    daily = datetime.combine(day, time(8), SHANGHAI)
    if daily > after:
        return daily
    if day.weekday() in (0, 2, 5) and stored_date != day:
        first = datetime.combine(day, time(21, 35), SHANGHAI)
        for minutes in range(0, 141, 10):
            slot = first + timedelta(minutes=minutes)
            if slot > after:
                return slot
    return daily + timedelta(days=1)


def log(event, **fields):
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, default=str), flush=True)


def log_error(exc, mode):
    reason = str(exc) if isinstance(exc, IngestError) else type(exc).__name__
    log("dlt_sync_failed", mode=mode, error=reason, sqlstate=getattr(exc, "sqlstate", None))


def watch(dsn):
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    stored_date = None
    while not stop.is_set():
        try:
            result = ingest(dsn, "sync")
            stored_date = result["stored_latest_date"]
            log("dlt_sync", mode="watch", **result)
        except (IngestError, psycopg.Error) as exc:
            log_error(exc, "watch")
        deadline = next_run(datetime.now(SHANGHAI), stored_date)
        log("dlt_next_run", at=deadline.isoformat())
        while not stop.is_set():
            remaining = (deadline - datetime.now(SHANGHAI)).total_seconds()
            if remaining <= 0:
                break
            stop.wait(min(60, remaining))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    backfill = commands.add_parser("backfill", help="Import the official history")
    backfill.add_argument("--through-issue", help="Override the last issue to import, using official YYNNN")
    commands.add_parser("sync", help="Catch up with the latest verified official result")
    commands.add_parser("watch", help="Run the draw-day schedule with automatic catch-up")
    commands.add_parser("migrate", help="Apply the Next database schema before the first import")
    args = parser.parse_args()
    through = getattr(args, "through_issue", None)
    if through is not None and (not ISSUE.fullmatch(through) or through < FIRST_ISSUE):
        parser.error("--through-issue must be a YYNNN issue starting at 07001")
    try:
        settings = Settings.from_env()
        dsn = settings.database_url
        target = conninfo_to_dict(dsn)
        if (target.get("host"), target.get("dbname")) != ("next-database", "dehps_next"):
            raise IngestError("The importer requires the Next database at next-database/dehps_next")
        if args.command == "migrate":
            db = Database(settings)
            try:
                version = db.migrate()
            finally:
                db.close()
            log("dlt_schema_ready", version=version)
        elif args.command == "watch":
            watch(dsn)
        else:
            log("dlt_sync", mode=args.command, **ingest(dsn, args.command, through))
    except (IngestError, psycopg.Error, PoolTimeout) as exc:
        log_error(exc, args.command)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
