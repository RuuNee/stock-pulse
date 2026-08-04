"""예약된 브리핑 실행이 지금 실제로 발송해야 하는지 판정한다.

배경: GitHub Actions 의 schedule 은 예약 시각을 보장하지 않는다. 이 저장소
실측 지연은 6분에서 202분까지 벌어졌고, 2026-07-28 국장 브리핑은 23:11Z 예약이
00:09Z(=09:09 KST)에 깨어나면서 통째로 발송되지 않았다.

그래서 워크플로는 목표 시각 앞뒤로 슬롯을 여러 개 예약하고, 깨어난 슬롯마다
이 판정을 먼저 돌린다. 창 밖이면 몇 초 만에 끝나므로 남는 슬롯은 사실상 공짜다.

판정 순서(먼저 걸리는 쪽이 이긴다):
  1. 수동 실행(--force)  → 무조건 발송
  2. 휴장일             → 발송 안 함
  3. 오늘자 브리핑 파일이 이미 있음 → 중복 발송 안 함
  4. 현지 시각이 발송 창 밖 → 발송 안 함 (개장 후 브리핑 방지)
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path

import json

from .config import BRIEF_WINDOW, DATA_DIR
from .util.dates import (
    is_trading_day, next_session_date, now_et, now_kst, session_closed,
)


def local_now(market: str) -> datetime:
    """브리핑 기준이 되는 현지 시각. 국장은 KST, 미장은 ET."""
    return now_kst() if market == "KR" else now_et()


def last_closed_session(market: str, now: datetime | None = None) -> date | None:
    """지금 시점에서 **이미 끝난** 가장 최근 거래일."""
    local = now or local_now(market)
    day = local.date()
    for _ in range(14):
        if is_trading_day(market, day) and session_closed(market, day, local):
            return day
        day -= timedelta(days=1)
    return None


def data_stale(market: str, now: datetime | None = None,
               data_dir: Path | None = None) -> tuple[bool, str]:
    """이 시장의 종목 데이터가 마지막 마감 세션보다 뒤처졌는가.

    data-sync 슬롯이 "지금 돌 필요가 있나"를 15초 안에 답하는 데 쓴다.
    `pip install` 전에 판정해야 해서 표준 라이브러리만 쓴다 — pandas 를
    불러오면 그것만으로 슬롯 하나가 1분이 된다.

    2026-08-04 에 국장이 15:30 KST 에 마감했는데 스케줄러가 155분 밀려
    19:13 KST 에야 데이터가 들어왔다. 그 3시간 43분 동안 화면은 전날 종가를
    보여줬다(LS ELECTRIC 188,400 vs 실제 마감 197,000). 슬롯을 여러 개 깔고
    이 판정으로 거르면 먼저 깨어난 슬롯이 처리한다.
    """
    session = last_closed_session(market, now)
    if session is None:
        return False, f"{market}: 최근 2주 안에 끝난 거래일 없음 — 건너뜀"

    path = (data_dir or DATA_DIR) / "tickers" / "index.json"
    try:
        items = json.loads(path.read_text(encoding="utf-8")).get("items", [])
    except (OSError, ValueError):
        return True, f"{market}: index.json 을 읽을 수 없음 — 빌드합니다"

    dates = [it.get("date") for it in items
             if it.get("market") == market and it.get("date")]
    if not dates:
        return True, f"{market}: 데이터 없음 — 빌드합니다"

    have = max(dates)
    if have >= session.isoformat():
        return False, f"{market}: 이미 {have} 까지 있음 — 건너뜁니다"
    return True, f"{market}: {have} → {session.isoformat()} 갱신 필요"


def brief_path(market: str, session: date, data_dir: Path | None = None) -> Path:
    return (data_dir or DATA_DIR) / "brief" / f"{session.isoformat()}-{market}.json"


def window(market: str) -> tuple[time, time]:
    start, end = BRIEF_WINDOW[market]
    return _hhmm(start), _hhmm(end)


def decide(market: str, *, force: bool = False, now: datetime | None = None,
           data_dir: Path | None = None) -> tuple[bool, str]:
    """(발송할지, 사람이 읽을 이유)를 돌려준다."""
    market = market.upper()
    if market not in BRIEF_WINDOW:
        raise ValueError(f"unknown market: {market}")

    if force:
        return True, "수동 실행 — 시각·중복 검사 생략"

    now = now or local_now(market)
    today = now.date()
    if not is_trading_day(market, today):
        return False, f"{today} 휴장일 — 발송 없음"

    session = next_session_date(market, now)
    path = brief_path(market, session, data_dir)
    if path.exists():
        return False, f"{path.name} 이미 있음 — 중복 발송 방지"

    start, end = window(market)
    label = now.strftime("%H:%M")
    span = f"{start.strftime('%H:%M')}~{end.strftime('%H:%M')}"
    if now.time() < start:
        return False, f"현재 {label} — 발송 창({span}) 전, 다음 슬롯이 처리합니다"
    if now.time() > end:
        return False, f"현재 {label} — 발송 창({span}) 후, 스케줄러 지연으로 이 슬롯은 버립니다"
    return True, f"현재 {label} — 발송 창({span}) 안, 발송합니다"


def next_send(market: str, now: datetime | None = None,
              data_dir: Path | None = None) -> tuple[datetime, datetime] | None:
    """다음으로 브리핑이 나갈 발송 창 (시작, 끝). 현지 시각 기준.

    "왜 아직 안 왔지"에 답하기 위한 것이다 — 오늘 창이 아직 안 지났고 브리핑도
    없으면 오늘 창을, 이미 나갔거나 창이 지났으면 다음 거래일 창을 돌려준다.
    """
    market = market.upper()
    now = now or local_now(market)
    start_t, end_t = window(market)
    day = now.date()
    for _ in range(14):
        if is_trading_day(market, day):
            end_dt = datetime.combine(day, end_t, tzinfo=now.tzinfo)
            if end_dt > now and not brief_path(market, day, data_dir).exists():
                return datetime.combine(day, start_t, tzinfo=now.tzinfo), end_dt
        day += timedelta(days=1)
    return None


def _hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))
