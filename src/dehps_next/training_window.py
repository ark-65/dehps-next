"""Draw-day17:00 pause, released only by an observed complete official-result receipt."""

from datetime import datetime, time, timedelta

from .calendar import CALENDAR, ZONE
from .data import CWL_URL
from .domain import now

TRAINING_KINDS = frozenset({"TRAIN", "RESEARCH_EVALUATE", "RESEARCH_PLAN"})


def status(c, at=None):
    clock = (at or now()).astimezone(ZONE)
    if not CALENDAR["valid_from"] <= clock.date().isoformat() <= CALENDAR["valid_until"]:
        return {"paused": True, "reason": "CALENDAR_REVIEW_REQUIRED", "at": clock.isoformat()}
    day = clock.date()
    for _ in range(8):
        prepare = datetime.combine(day, time.fromisoformat(CALENDAR["prepare_time"]), ZONE)
        if day.weekday() in CALENDAR["weekdays"] and prepare <= clock:
            break
        day -= timedelta(days=1)
    if day.isoformat() < CALENDAR["valid_from"]:
        return {"paused": False, "reason": "BEFORE_FIRST_VERIFIED_WINDOW", "at": clock.isoformat()}
    draw = datetime.combine(day, time.fromisoformat(CALENDAR["draw_time"]), ZONE)
    start = datetime.combine(day, time.min, ZONE)
    rows = c.execute(
        """SELECT d.issue,p.first_verified_at,p.source_id FROM draws d
        JOIN official_publications p ON p.issue=d.issue JOIN sources s ON s.id=p.source_id
        WHERE d.draw_at>=%s AND d.draw_at<%s AND d.draw_at<=%s
          AND p.first_verified_at>=%s AND p.first_verified_at<=%s
          AND s.observed_at>=%s AND s.observed_at<=%s AND s.url=%s
          AND s.provenance LIKE 'OFFICIAL_CWL%%'
          AND p.provenance='OFFICIAL_CWL_COMPLETE_LABEL_FIRST_VERIFIED_IN_NEXT'
        ORDER BY d.issue LIMIT 2""",
        (start, start + timedelta(days=1), clock, draw, clock, draw, clock, CWL_URL),
    ).fetchall()
    verified = rows[0] if len(rows) == 1 and clock >= draw else None
    return {
        "paused": verified is None,
        "reason": "OFFICIAL_DRAW_VERIFIED" if verified else "WAITING_OFFICIAL_DRAW_VERIFICATION",
        "at": clock.isoformat(),
        "draw_day": day.isoformat(),
        "pause_from": prepare.isoformat(),
        "draw_not_before": draw.isoformat(),
        "verified_issue": verified["issue"] if verified else None,
        "verified_at": verified["first_verified_at"].isoformat() if verified else None,
        "source_id": verified["source_id"] if verified else None,
        "resume": "COMPLETE_OFFICIAL_RECEIPT;NOT_CLOCK_ONLY_OR_NEXT_MIDNIGHT",
    }
