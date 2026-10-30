"""Verified finite calendar, not an extrapolation of unknown next-year issue numbers."""

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from .errors import DomainError

ZONE = ZoneInfo("Asia/Shanghai")
CALENDAR = {
    "valid_from": "2026-10-05",
    "valid_until": "2026-12-31",
    "weekdays": [1, 3, 6],
    "draw_time": "21:15",
    "prepare_time": "17:00",
    "seal_time": "17:00",
    "mail_time": "17:00",
    "deadline_time": "19:30",
    "policy": "pause-finalize-send-v4",
    "deadline_note": "Finalize and send immediately after17:00 pause;19:30 is only an outage failsafe before20:00, never a scheduled wait",
    "rules_source": "https://www.swlc.net.cn/lottery/ssq.html?limit=30&view=previous",
    "closure_source": "https://www.gdfc.org.cn/datas/content/content_280552.html?subjectID=91",
    "closure_note": "2026 National Day closure ends October4; policy coverage starts October5",
}


def next_target(latest):
    day = latest["draw_at"].astimezone(ZONE).date() + timedelta(days=1)
    while day.weekday() not in CALENDAR["weekdays"]:
        day += timedelta(days=1)
    if not date.fromisoformat(CALENDAR["valid_from"]) <= day <= date.fromisoformat(CALENDAR["valid_until"]):
        raise DomainError("CALENDAR_REVIEW_REQUIRED", "No verified calendar for this draw day")
    if int(latest["issue"][:4]) != day.year:
        raise DomainError("ISSUE_ROLLOVER_REVIEW", "Do not guess cross-year issue numbering")
    return {
        "issue": str(int(latest["issue"]) + 1),
        "day": day,
        **{
            key: datetime.combine(day, time.fromisoformat(CALENDAR[key]), ZONE)
            for key in ("draw_time", "prepare_time", "seal_time", "mail_time", "deadline_time")
        },
    }
