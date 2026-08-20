"""실적 발표 일정 (미국).

이 프로젝트가 여태 답하던 질문은 "왜 움직였나" — 전부 사후다. 뉴스는 급등의
**원인**이라 나온 순간 이미 가격에 들어가 있고, 그래서 뉴스만으로는 아무리
빨라도 늦는다. 미리 알 수 있는 건 **일정**뿐이다. 급등을 예측할 수는 없어도
"오늘 밤 이 종목이 실적을 발표한다"는 미리 말할 수 있다.

소스는 Nasdaq 의 공개 실적 캘린더 JSON (키 불필요). 프로젝트 기본
`USER_AGENT` 로는 응답이 오지 않아 브라우저 UA 를 쓴다 — 2026-08-20 실측으로
기본 UA 는 25초 타임아웃, 브라우저 UA 는 3.1초.

한국 실적 일정은 아직 없다. DART 오픈API 가 후보인데 발급 키가 필요해서
`GEMINI_API_KEY` 처럼 시크릿 관리가 붙는다 — 별도 작업으로 남긴다.
"""

from __future__ import annotations

import json
import urllib.request
from datetime import date, timedelta

from ..config import (
    CALENDAR_BROWSER_UA,
    CALENDAR_DAYS_AHEAD,
    CALENDAR_MIN_MARCAP,
    HTTP_TIMEOUT,
    NASDAQ_EARNINGS_URL,
)
from ..util import io, log

_CACHE_TTL = 60 * 60 * 6


def _fetch_day(day: date) -> list[dict]:
    url = NASDAQ_EARNINGS_URL.format(date=day.isoformat())
    req = urllib.request.Request(
        url, headers={"User-Agent": CALENDAR_BROWSER_UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        payload = json.loads(resp.read())
    return ((payload.get("data") or {}).get("rows") or [])


def fetch_earnings(start: date | None = None,
                   days: int = CALENDAR_DAYS_AHEAD) -> list[dict]:
    """`start` 부터 `days` 일치 미국 실적 발표 일정.

    하루가 100건 가까이 나오는 시즌이 있어 시가총액으로 먼저 거른다. 브리핑에
    "들어 본 적 없는 스몰캡 40개"를 싣는 건 노이즈다.
    """
    start = start or date.today()
    cache_key = f"earnings_{start.isoformat()}_{days}"
    cached = io.cache_get(cache_key, _CACHE_TTL)
    if cached is not None:
        return cached

    out: list[dict] = []
    for offset in range(days):
        day = start + timedelta(days=offset)
        if day.weekday() >= 5:      # 주말엔 발표가 없다
            continue
        try:
            rows = _fetch_day(day)
        except Exception as exc:
            log.warn(f"earnings calendar {day}: {exc}")
            continue
        for row in rows:
            item = _normalize(row, day)
            if item:
                out.append(item)

    out.sort(key=lambda x: (x["date"], -(x["marcap"] or 0)))
    io.cache_set(cache_key, out)
    log.ok(f"earnings calendar: {len(out)} entries ({days}d)")
    return out


def _normalize(row: dict, day: date) -> dict | None:
    symbol = (row.get("symbol") or "").strip().upper()
    if not symbol:
        return None
    marcap = _money(row.get("marketCap"))
    if marcap is not None and marcap < CALENDAR_MIN_MARCAP:
        return None
    return {
        "date": day.isoformat(),
        "code": symbol,
        "market": "US",
        "name": (row.get("name") or symbol).strip(),
        # time-pre-market / time-after-hours / time-not-supplied
        "when": _when(row.get("time")),
        "epsForecast": (row.get("epsForecast") or "").strip() or None,
        "marcap": marcap,
    }


def _when(value: str | None) -> str:
    text = (value or "").lower()
    if "pre-market" in text:
        return "개장 전"
    if "after-hours" in text:
        return "장 마감 후"
    return "시간 미정"


def _money(value: str | None) -> int | None:
    """`"$916,770,718,656"` → 916770718656."""
    if not value:
        return None
    digits = "".join(c for c in str(value) if c.isdigit())
    return int(digits) if digits else None
