"""`status` — 브리핑이 지금 어떤 상태인지 한 화면에.

브리핑은 하루 한 번, 개장 직전 몇십 분 안에만 나간다. 그 밖의 시간에는 "고장난
것"과 "아직 때가 아닌 것"이 겉보기에 똑같다. 2026-07-28 에 실제로 그게 문제였다 —
발송이 안 된 날에도, 정상적으로 대기 중인 날에도 화면상 차이가 없었다.

그래서 판정 근거(세션 일자·파일 유무·발송 창·현재 시각·게이트 결정)와 다음 발송
예정 시각을 한 번에 찍는다. 게이트 판정은 실제 워크플로가 쓰는 함수를 그대로 부른다.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta

from .config import ROOT
from .gate import brief_path, decide, local_now, next_send, window
from .util.dates import next_session_date

WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]
_TZ_LABEL = {"KR": "KST", "US": "ET"}


def report(markets: tuple[str, ...] = ("KR", "US")) -> str:
    lines = lag_lines(git_behind(), fetch_age())
    for market in markets:
        lines.extend(_market_block(market.upper()))
        lines.append("")
    return "\n".join(lines).rstrip()


def _market_block(market: str) -> list[str]:
    now = local_now(market)
    tz = _TZ_LABEL[market]
    session = next_session_date(market, now)
    path = brief_path(market, session)
    start, end = window(market)
    # 같은 `now` 를 넘긴다 — 따로 읽으면 분 경계에서 표시 시각과 판정 근거가 어긋난다.
    run, reason = decide(market, now=now)

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


# --------------------------------------------------------------------------
# 로컬 트리가 낡았는지
#
# 브리핑 파일 유무는 로컬 `data/` 를 보고 판정한다. 발송은 GitHub Actions 에서
# 일어나고 워크플로가 브리핑을 main 에 커밋하므로, `git pull` 을 안 한 상태에서는
# 이미 나간 브리핑도 "없음" 으로 보인다. 2026-07-28 미장 브리핑이 실제로 그랬다 —
# 원격에는 있는데 로컬이 4커밋 뒤처져 미발송처럼 보였다.
# --------------------------------------------------------------------------
def lag_lines(behind: int | None, fetched_ago: timedelta | None) -> list[str]:
    """뒤처져 있으면 경고 블록, 아니면 빈 리스트."""
    if not behind:
        return []
    when = f", 마지막 fetch {_ago(fetched_ago)}" if fetched_ago is not None else ""
    return [
        f"! 로컬이 origin/main 보다 {behind}커밋 뒤{when}",
        "  아래 '브리핑 파일 없음' 이 미발송이 아닐 수 있습니다 — git pull 후 다시 보세요",
        "",
    ]


def git_behind() -> int | None:
    """origin/main 보다 몇 커밋 뒤인지. 네트워크는 타지 않는다 — 마지막 fetch 기준.

    그래서 `fetch_age()` 를 같이 보여 준다. fetch 자체가 오래됐으면 이 수치도
    낡은 것이고, 0 이라고 최신이라는 뜻이 아니다.
    """
    out = _git("rev-list", "--count", "HEAD..origin/main")
    return int(out) if out and out.isdigit() else None


def fetch_age() -> timedelta | None:
    """마지막 `git fetch`/`pull` 이후 경과 시간."""
    try:
        stamp = (ROOT / ".git" / "FETCH_HEAD").stat().st_mtime
    except OSError:
        return None   # 한 번도 fetch 안 했거나 .git 이 파일(워크트리)
    return datetime.now() - datetime.fromtimestamp(stamp)


def _git(*args: str) -> str | None:
    try:
        done = subprocess.run(("git", *args), cwd=ROOT, capture_output=True,
                              text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None   # git 이 없거나 저장소가 아님 — 경고를 생략한다
    return done.stdout.strip() if done.returncode == 0 else None


def _ago(delta: timedelta) -> str:
    minutes = max(0, int(delta.total_seconds()) // 60)
    if minutes < 60:
        return f"{minutes}분 전"
    hours, _ = divmod(minutes, 60)
    return f"{hours}시간 전" if hours < 24 else f"{hours // 24}일 전"


def run(markets: tuple[str, ...] = ("KR", "US")) -> int:
    print(report(markets))
    return 0
