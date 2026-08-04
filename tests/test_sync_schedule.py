"""data-sync 가 **개장 1시간 전까지 반드시 끝나는지** 슬롯 배치로 검증한다.

요구사항: "오래 걸려도 장 시작 1시간 전에는 도착할 수 있게."

두 가지가 동시에 커진다 —
  · 유니버스가 291종목이 되면서 실행이 국장 18분 / 미장 25분으로 늘었다.
  · GitHub 스케줄러 지연은 여전히 최대 실측 202분(테스트는 240분으로 잡는다).

둘을 더해도 마감선 안에 들어오는 슬롯이 시장마다 **2개 이상** 있어야 한다.
하나뿐이면 그 슬롯이 실패하는 날 개장 때까지 낡은 데이터가 남는다.
cron 을 손대면 여기서 먼저 깨진다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

WORKFLOW = (Path(__file__).resolve().parent.parent
            / ".github" / "workflows" / "data-sync.yml")

MAX_DELAY_MIN = 240      # 실측 최대 202분 + 여유
RUN_MIN = {"KR": 25, "US": 35}   # 실측 추정(18/25)에 40% 여유
LEAD_MIN = 60            # 개장 이 시간 전까지는 끝나 있어야 한다
DAY = 24 * 60

# (마감, 다음 개장) — UTC 분. 미장은 서머타임/겨울 둘 다 본다.
SESSIONS = {
    "KR": (6 * 60 + 30, 0),               # 15:30 KST / 09:00 KST
    "US-EDT": (20 * 60, 13 * 60 + 30),    # 16:00 ET / 09:30 ET
    "US-EST": (21 * 60, 14 * 60 + 30),
}
RUN_FOR = {"KR": "KR", "US-EDT": "US", "US-EST": "US"}


def slots_utc() -> list[int]:
    found = re.findall(r'-\s*cron:\s*"(\d+)\s+(\d+)\s', WORKFLOW.read_text(encoding="utf-8"))
    assert found, "data-sync.yml 에서 cron 을 못 찾았습니다"
    return sorted(int(h) * 60 + int(m) for m, h in found)


def usable(session: str) -> list[int]:
    """마감 이후에 깨어나고, 최대 지연을 먹어도 마감선 안에 끝나는 슬롯."""
    close, open_ = SESSIONS[session]
    run = RUN_MIN[RUN_FOR[session]]
    deadline = (open_ - LEAD_MIN - close) % DAY      # 마감 기준 경과 분
    out = []
    for slot in slots_utc():
        since_close = (slot - close) % DAY
        if since_close == 0:
            continue                                  # 마감과 동시 — 아직 데이터가 없다
        if since_close + MAX_DELAY_MIN + run <= deadline:
            out.append(slot)
    return out


@pytest.mark.parametrize("session", list(SESSIONS))
def test_two_slots_finish_before_the_open_deadline(session):
    """시장마다 마감선을 지키는 슬롯이 2개 이상 — 하나는 실패해도 된다."""
    ok = usable(session)

    assert len(ok) >= 2, (
        f"{session}: 최대 지연({MAX_DELAY_MIN}분) + 실행({RUN_MIN[RUN_FOR[session]]}분)을 "
        f"먹고도 개장 {LEAD_MIN}분 전까지 끝나는 슬롯이 {len(ok)}개뿐입니다. "
        f"슬롯을 앞당기거나 더 까세요."
    )


@pytest.mark.parametrize("session", list(SESSIONS))
def test_a_slot_fires_right_after_the_close(session):
    """마감 직후 슬롯이 있어야 평소에 빨리 들어온다.

    마감선만 지키면 개장 직전에 몰아서 돌려도 통과한다 — 그건 요구사항의
    글자만 지키고 뜻은 어긴 것이다. 정상적인 날엔 마감 후 곧바로 받아야 한다.
    """
    close, _ = SESSIONS[session]
    soon = [s for s in slots_utc() if 0 < (s - close) % DAY <= 60]

    assert soon, f"{session}: 마감 후 1시간 안에 깨어나는 슬롯이 없습니다"


def test_run_estimate_has_headroom_over_measured():
    """실측이 늘면 이 테스트가 먼저 알려 주게 — 추정치에 여유를 둔 이유를 고정한다."""
    assert RUN_MIN["KR"] > 18 and RUN_MIN["US"] > 25
