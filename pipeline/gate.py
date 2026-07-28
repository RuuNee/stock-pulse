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

from datetime import date, datetime, time
from pathlib import Path

from .config import BRIEF_WINDOW, DATA_DIR
from .util.dates import is_trading_day, next_session_date, now_et, now_kst


def local_now(market: str) -> datetime:
    """브리핑 기준이 되는 현지 시각. 국장은 KST, 미장은 ET."""
    return now_kst() if market == "KR" else now_et()


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


def _hhmm(value: str) -> time:
    hour, minute = value.split(":")
    return time(int(hour), int(minute))
