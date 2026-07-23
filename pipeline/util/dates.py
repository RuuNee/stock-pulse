"""Time helpers.

Storage is always UTC ISO8601 with a trailing Z (md파일/02-데이터스키마.md §7).
Only presentation converts to KST/ET.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from ..config import ET, KST

WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]

# Fixed-date Korean holidays plus the lunar/substitute days that fall inside the
# window this project cares about. Missing an entry only means one extra brief.
KR_HOLIDAYS_2026 = {
    "2026-01-01", "2026-02-16", "2026-02-17", "2026-02-18", "2026-03-01",
    "2026-03-02", "2026-05-01", "2026-05-05", "2026-05-24", "2026-05-25",
    "2026-06-03", "2026-06-06", "2026-08-15", "2026-08-17", "2026-09-24",
    "2026-09-25", "2026-09-26", "2026-10-03", "2026-10-05", "2026-10-09",
    "2026-12-25", "2026-12-31",
}
US_HOLIDAYS_2026 = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """UTC ISO8601 with Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def now_kst() -> datetime:
    return datetime.now(KST)


def now_et() -> datetime:
    return datetime.now(ET)


def kst_label(dt: datetime | None = None) -> str:
    dt = dt or now_kst()
    return f"{dt.year}년 {dt.month}월 {dt.day}일 {WEEKDAY_KR[dt.weekday()]}요일"


def next_session_date(market: str) -> date:
    """The trading day the upcoming brief is about.

    The KR brief runs at 07:30 KST, so the session is *today*. The US brief runs
    at 21:30 KST, which is still the same US calendar day in New York.
    """
    local = now_kst() if market == "KR" else now_et()
    d = local.date()
    for _ in range(10):
        if is_trading_day(market, d):
            return d
        d += timedelta(days=1)
    return d


def is_trading_day(market: str, d: date) -> bool:
    if d.weekday() >= 5:
        return False
    key = d.isoformat()
    holidays = KR_HOLIDAYS_2026 if market == "KR" else US_HOLIDAYS_2026
    return key not in holidays


def days_ago(n: int) -> datetime:
    return now_utc() - timedelta(days=n)
