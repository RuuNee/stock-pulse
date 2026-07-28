"""`status` — 브리핑이 지금 어떤 상태인지 한 화면에.

브리핑은 하루 한 번, 개장 직전 몇십 분 안에만 나간다. 그 밖의 시간에는 "고장난
것"과 "아직 때가 아닌 것"이 겉보기에 똑같다. 2026-07-28 에 실제로 그게 문제였다 —
발송이 안 된 날에도, 정상적으로 대기 중인 날에도 화면상 차이가 없었다.

그래서 판정 근거(세션 일자·파일 유무·발송 창·현재 시각·게이트 결정)와 다음 발송
예정 시각을 한 번에 찍는다. 게이트 판정은 실제 워크플로가 쓰는 함수를 그대로 부른다.
"""

from __future__ import annotations

from datetime import datetime

from .config import BRIEF_WINDOW
from .gate import brief_path, decide, local_now, next_send, window
from .util.dates import next_session_date

WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]
_TZ_LABEL = {"KR": "KST", "US": "ET"}


def report(markets: tuple[str, ...] = ("KR", "US")) -> str:
    lines: list[str] = []
    for market in markets:
        lines.extend(_market_block(market.upper()))
        lines.append("")
    return "\n".join(lines).rstrip()


def _market_block(market: str) -> list[str]:
    now = local_now(market)
    tz = _TZ_LABEL[market]
    session = next_session_date(market)
    path = brief_path(market, session)
    start, end = window(market)
    run, reason = decide(market)

    out = [
        f"[{market}]  세션 {session} ({WEEKDAY_KR[session.weekday()]})"
        f"  ·  현재 {now:%H:%M} {tz}",
        f"  브리핑 파일   {_file_line(path)}",
        f"  발송 창       {start:%H:%M}~{end:%H:%M} {tz}",
        f"  게이트        {'발송' if run else '대기'} — {reason}",
    ]

    upcoming = next_send(market, now)
    if upcoming is None:
        out.append("  다음 발송     2주 안에 없음 — 휴장일 표를 확인하세요")
    else:
        out.append(f"  다음 발송     {_upcoming_line(upcoming, now, tz)}")
    return out


def _file_line(path) -> str:
    if not path.exists():
        return f"없음 ({path.name})"
    size = path.stat().st_size
    return f"있음 ({path.name}, {size:,}B)"


def _upcoming_line(upcoming: tuple[datetime, datetime], now: datetime, tz: str) -> str:
    start, end = upcoming
    when = f"{start:%Y-%m-%d} {start:%H:%M}~{end:%H:%M} {tz}"
    if start <= now <= end:
        return f"{when} — 지금이 발송 창입니다"
    delta = start - now
    hours, minutes = divmod(int(delta.total_seconds()) // 60, 60)
    ago = f"{hours}시간 {minutes}분 뒤" if hours else f"{minutes}분 뒤"
    return f"{when} ({ago})"


def run(markets: tuple[str, ...] = ("KR", "US")) -> int:
    print(report(markets))
    # 창 계산이 어긋나 있으면(BRIEF_WINDOW 오타 등) 여기서 드러난다.
    for market in markets:
        assert market.upper() in BRIEF_WINDOW
    return 0
