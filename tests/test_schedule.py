"""워크플로 cron 슬롯이 스케줄러 지연을 실제로 흡수하는지 검증한다.

2026-07-28 국장 브리핑 미발송은 코드 버그가 아니라 배치 문제였다. 슬롯이 2개
(23:11Z, 23:23Z)뿐이었는데 GitHub 이 둘 다 ~55분 밀려 깨우는 바람에 발송 창을
같이 놓쳤다. 그래서 "지연이 0~240분 어디에 걸리든 최소 한 슬롯은 창 안에
떨어진다"를 테스트로 고정한다. cron 을 손대면 여기서 먼저 깨진다.

실측 지연(이 저장소 워크플로 로그): +6, +51, +58, +89, +114, +202 분.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pipeline.config import BRIEF_LATE_CUTOFF, BRIEF_WINDOW

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"

MAX_DELAY_MIN = 240   # 실측 최대 202분 + 여유
DAY = 24 * 60

# 발송 창을 UTC 로 옮길 때 쓰는 현지 시간대 오프셋 (시간 단위).
UTC_OFFSET = {"KR": +9, "US-EDT": -4, "US-EST": -5}


def _minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def slots_utc(workflow: str) -> list[int]:
    """워크플로의 cron 예약 시각을 자정 기준 UTC 분으로."""
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    found = re.findall(r'-\s*cron:\s*"(\d+)\s+(\d+)\s', text)
    assert found, f"{workflow}: cron 을 못 찾았습니다"
    return sorted(int(hour) * 60 + int(minute) for minute, hour in found)


def window_utc(market: str, offset_hours: int) -> tuple[int, int]:
    """현지 발송 창 → 자정 기준 UTC 분 구간 (0~1439, 자정을 넘을 수 있다)."""
    start, end = BRIEF_WINDOW[market]
    shift = offset_hours * 60
    return (_minutes(start) - shift) % DAY, (_minutes(end) - shift) % DAY


def sends(slots: list[int], window: tuple[int, int], delay: int) -> bool:
    """지연이 `delay`분일 때 발송 창 안에 깨어나는 슬롯이 하나라도 있는가."""
    start, end = window
    for slot in slots:
        woke = (slot + delay) % DAY
        inside = start <= woke <= end if start <= end else (woke >= start or woke <= end)
        if inside:
            return True
    return False


def assert_full_coverage(slots, window, label):
    missed = [d for d in range(MAX_DELAY_MIN + 1) if not sends(slots, window, d)]
    assert not missed, f"{label}: 지연 {missed[:10]}분(총 {len(missed)}개)에 발송 슬롯이 없습니다"


@pytest.mark.parametrize("delay", [0, 6, 51, 58, 89, 114, 202])
def test_kr_absorbs_observed_delays(delay):
    """실제로 관측된 지연들은 반드시 발송으로 이어진다."""
    assert sends(slots_utc("brief-kr.yml"), window_utc("KR", UTC_OFFSET["KR"]), delay)


def test_kr_covers_every_delay_up_to_4h():
    assert_full_coverage(slots_utc("brief-kr.yml"), window_utc("KR", UTC_OFFSET["KR"]), "brief-kr")


@pytest.mark.parametrize("season", ["US-EDT", "US-EST"])
def test_us_covers_every_delay_in_both_dst_seasons(season):
    """cron 은 UTC 고정이라 서머타임 양쪽 계절을 각각 덮어야 한다."""
    window = window_utc("US", UTC_OFFSET[season])
    assert_full_coverage(slots_utc("brief-us.yml"), window, f"brief-us {season}")


@pytest.mark.parametrize("workflow,market", [("brief-kr.yml", "KR"), ("brief-us.yml", "US")])
def test_slot_spacing_never_exceeds_window_width(workflow, market):
    """슬롯 간격이 창 너비보다 넓으면 특정 지연대가 통째로 빈다."""
    start, end = BRIEF_WINDOW[market]
    width = _minutes(end) - _minutes(start)
    slots = slots_utc(workflow)
    gaps = [b - a for a, b in zip(slots, slots[1:])]
    assert max(gaps) <= width, f"{workflow}: 슬롯 간격 {max(gaps)}분 > 발송 창 {width}분"


# --------------------------------------------------------------------------
# 슬롯 배치로는 못 막는 형태 — 2026-08-07 의 "한 덩어리 방출"
# --------------------------------------------------------------------------
# 위 테스트들은 전부 "지연이 슬롯마다 비슷하게 붙는다"를 가정한다. 그날 GitHub 은
# 그러지 않았다. 240분에 걸쳐 예약된 슬롯 7개를 61분 안에 몰아서 깨웠고, 배치가
# 접히면서 전부 창 뒤로 넘어갔다. 슬롯을 늘리는 대응이 왜 안 통하는지를 여기 박아
# 둔다 — 이 케이스를 구하는 건 슬롯이 아니라 지각 마감이다.
BURST_2026_08_07_KST = ["09:44", "09:50", "09:57", "10:03", "10:29", "10:38", "10:45"]


def test_a_clustered_release_defeats_slot_spreading():
    """실제 방출 시각 7개 중 발송 창 안에 떨어진 게 하나도 없다."""
    start, end = _minutes(BRIEF_WINDOW["KR"][0]), _minutes(BRIEF_WINDOW["KR"][1])
    woke = [_minutes(t) for t in BURST_2026_08_07_KST]
    assert not [w for w in woke if start <= w <= end]


def test_the_late_cutoff_rescues_that_release():
    """같은 방출을 지각 마감이 받아낸다 — 안 그러면 그날 브리핑이 통째로 없다."""
    start = _minutes(BRIEF_WINDOW["KR"][0])
    cutoff = _minutes(BRIEF_LATE_CUTOFF["KR"])
    woke = [_minutes(t) for t in BURST_2026_08_07_KST]
    assert [w for w in woke if start <= w <= cutoff]


@pytest.mark.parametrize("market", ["KR", "US"])
def test_late_cutoff_sits_after_the_window(market):
    """마감이 창보다 앞이면 지각 발송 경로가 영영 안 열린다."""
    assert _minutes(BRIEF_LATE_CUTOFF[market]) > _minutes(BRIEF_WINDOW[market][1])


@pytest.mark.parametrize("workflow,days", [("brief-kr.yml", "0-4"), ("brief-us.yml", "1-5")])
def test_weekday_spec(workflow, days):
    """국장 슬롯은 전날 UTC(일~목), 미장 슬롯은 당일 UTC(월~금)에 예약돼야 한다."""
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    specs = set(re.findall(r'-\s*cron:\s*"\d+\s+\d+\s+\*\s+\*\s+([\d-]+)"', text))
    assert specs == {days}, f"{workflow}: 요일 지정이 {specs}"
