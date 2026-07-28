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

# 연도별로 나눠 둔다. 표가 없는 해는 "주말만 거르고 평일은 전부 개장"으로 동작하므로,
# 해가 바뀌면 공휴일에 브리핑이 나간다. 조용히 틀리지 않도록 doctor 가 커버 범위를
# 점검한다(`holiday_coverage_gap`). 새 해 목록을 넣을 때는 아래 dict 에 추가하면 된다.
#
# 여기서 막지 않고 흘려보내는 쪽을 택한 이유: 표가 없다고 발송을 멈추면 그 해 브리핑이
# 통째로 사라진다. 휴장일 몇 번 더 나가는 쪽이 낫다.
HOLIDAYS: dict[str, dict[int, set[str]]] = {
    "KR": {2026: KR_HOLIDAYS_2026},
    "US": {2026: US_HOLIDAYS_2026},
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


def next_session_date(market: str, now: datetime | None = None) -> date:
    """The trading day the upcoming brief is about.

    The KR brief runs in the 07:45~08:40 KST window, so the session is *today*.
    The US brief runs 08:15~09:10 ET, still the same US calendar day in New York.
    `now` is injectable so the gate can be tested at arbitrary clock positions.
    """
    local = now or (now_kst() if market == "KR" else now_et())
    d = local.date()
    for _ in range(10):
        if is_trading_day(market, d):
            return d
        d += timedelta(days=1)
    return d


def is_trading_day(market: str, d: date) -> bool:
    if d.weekday() >= 5:
        return False
    holidays = HOLIDAYS.get(market, {}).get(d.year)
    if holidays is None:
        return True   # 표가 없는 해 — 주말만 거른다. doctor 가 이 상태를 경고한다.
    return d.isoformat() not in holidays


def holiday_coverage_gap(market: str, through: date | None = None) -> list[int]:
    """`through`(기본: 오늘부터 1년 뒤)까지 중 휴장일 표가 없는 연도.

    비어 있지 않으면 그 해 공휴일에 브리핑이 나간다는 뜻이다.
    """
    start = now_kst().date() if market == "KR" else now_et().date()
    through = through or date(start.year + 1, start.month, start.day)
    covered = HOLIDAYS.get(market, {})
    return [y for y in range(start.year, through.year + 1) if y not in covered]


def days_ago(n: int) -> datetime:
    return now_utc() - timedelta(days=n)
