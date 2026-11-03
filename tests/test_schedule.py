"""워크플로 cron 슬롯이 스케줄러 지연을 실제로 흡수하는지 검증한다.

2026-07-28 국장 브리핑 미발송은 코드 버그가 아니라 배치 문제였다. 슬롯이 2개
(23:11Z, 23:23Z)뿐이었는데 GitHub 이 둘 다 ~55분 밀려 깨우는 바람에 발송 창을
같이 놓쳤다. 그 뒤로 "지연이 0~240분 어디에 걸리든 최소 한 슬롯은 창 안에
떨어진다"를 여기 고정했다.

2026-10 에 지연이 3.5~6.7시간으로 커지며 그 전제가 깨졌다 — 미장 브리핑이 3주 내내
개장 뒤에 나갔다. 지금은 슬롯이 하루 내내 2시간 간격이고, 창 시작
`BRIEF_MAX_WAIT_MIN` 분 안에 깬 슬롯은 창 시작까지 기다렸다가 보낸다. 그래서 슬롯이
쓸모 있는 구간은 창 하나가 아니라 [창 시작 − 최대 대기, 창 끝] 이고, 지연이
0~12시간 어디에 걸리든 그 구간에 깨는 슬롯이 있어야 한다. cron 을 손대면 여기서
먼저 깨진다.

실측 지연(이 저장소 워크플로 로그): +6, +51, +58, +89, +114, +202 분 (2026-07),
국장 +212~+239 분, 미장 +368~+400 분 (2026-10), 대부분 버려지고 남은 것도 +5~+10시간
(2026-11-03, 맨 아래 참고).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from pipeline.config import (
    BRIEF_LATE_CUTOFF, BRIEF_MAX_WAIT_MIN, BRIEF_WINDOW, CLOSE_BRIEF_WINDOW,
)

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"

MAX_DELAY_MIN = 12 * 60     # 실측 최대 400분(미장, 2026-10) + 여유
CLOSE_MAX_DELAY_MIN = 240   # 마감 브리핑은 창이 5시간이라 슬롯 배치만으로 덮는다
DAY = 24 * 60

# 발송 창을 UTC 로 옮길 때 쓰는 현지 시간대 오프셋 (시간 단위).
UTC_OFFSET = {"KR": +9, "US-EDT": -4, "US-EST": -5}

OBSERVED_DELAYS = [0, 6, 51, 58, 89, 114, 202, 212, 239, 368, 400]


def _minutes(hhmm: str) -> int:
    hour, minute = hhmm.split(":")
    return int(hour) * 60 + int(minute)


def _hours(field: str) -> list[int]:
    """cron 시 필드 → 시 목록. `7`, `0,2,4`, `*/2`, `1-23/2` 를 읽는다."""
    out = []
    for part in field.split(","):
        base, _, step = part.partition("/")
        if base == "*":
            lo, hi = 0, 23
        elif "-" in base:
            lo, hi = (int(x) for x in base.split("-"))
        else:
            lo = hi = int(base)
        out.extend(range(lo, hi + 1, int(step) if step else 1))
    return out


def slots_utc(workflow: str) -> list[int]:
    """워크플로의 cron 예약 시각을 자정 기준 UTC 분으로."""
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    found = re.findall(r'-\s*cron:\s*"(\d+)\s+(\S+)\s', text)
    assert found, f"{workflow}: cron 을 못 찾았습니다"
    return sorted(hour * 60 + int(minute) for minute, hours in found for hour in _hours(hours))


def band_utc(start: str, end: str, offset_hours: int, lead: int = 0) -> tuple[int, int]:
    """현지 [start − lead, end] → 자정 기준 UTC 분 구간 (자정을 넘을 수 있다)."""
    shift = offset_hours * 60
    return (_minutes(start) - lead - shift) % DAY, (_minutes(end) - shift) % DAY


def useful_band(market: str, offset_hours: int) -> tuple[int, int]:
    """깨어나면 정시 발송으로 이어지는 구간 = [창 시작 − 최대 대기, 창 끝]."""
    start, end = BRIEF_WINDOW[market]
    return band_utc(start, end, offset_hours, lead=BRIEF_MAX_WAIT_MIN)


def sends(slots: list[int], band: tuple[int, int], delay: int) -> bool:
    """지연이 `delay`분일 때 구간 안에 깨어나는 슬롯이 하나라도 있는가."""
    start, end = band
    for slot in slots:
        woke = (slot + delay) % DAY
        inside = start <= woke <= end if start <= end else (woke >= start or woke <= end)
        if inside:
            return True
    return False


def assert_full_coverage(slots, band, label, max_delay=MAX_DELAY_MIN):
    missed = [d for d in range(max_delay + 1) if not sends(slots, band, d)]
    assert not missed, f"{label}: 지연 {missed[:10]}분(총 {len(missed)}개)에 발송 슬롯이 없습니다"


@pytest.mark.parametrize("delay", OBSERVED_DELAYS)
def test_kr_absorbs_observed_delays(delay):
    """실제로 관측된 지연들은 반드시 정시 발송으로 이어진다."""
    assert sends(slots_utc("brief-kr.yml"), useful_band("KR", UTC_OFFSET["KR"]), delay)


@pytest.mark.parametrize("delay", OBSERVED_DELAYS)
@pytest.mark.parametrize("season", ["US-EDT", "US-EST"])
def test_us_absorbs_observed_delays(season, delay):
    assert sends(slots_utc("brief-us.yml"), useful_band("US", UTC_OFFSET[season]), delay)


def test_kr_covers_every_delay_up_to_12h():
    assert_full_coverage(slots_utc("brief-kr.yml"), useful_band("KR", UTC_OFFSET["KR"]), "brief-kr")


@pytest.mark.parametrize("season", ["US-EDT", "US-EST"])
def test_us_covers_every_delay_in_both_dst_seasons(season):
    """cron 은 UTC 고정이라 서머타임 양쪽 계절을 각각 덮어야 한다."""
    assert_full_coverage(slots_utc("brief-us.yml"), useful_band("US", UTC_OFFSET[season]),
                         f"brief-us {season}")


@pytest.mark.parametrize("workflow,market", [("brief-kr.yml", "KR"), ("brief-us.yml", "US")])
def test_slot_spacing_never_exceeds_the_useful_band(workflow, market):
    """슬롯 간격이 [창 시작 − 최대 대기, 창 끝] 보다 넓으면 특정 지연대가 통째로 빈다."""
    start, end = BRIEF_WINDOW[market]
    width = _minutes(end) - _minutes(start) + BRIEF_MAX_WAIT_MIN
    slots = slots_utc(workflow)
    gaps = [b - a for a, b in zip(slots, slots[1:])] + [slots[0] + DAY - slots[-1]]
    assert max(gaps) <= width, f"{workflow}: 슬롯 간격 {max(gaps)}분 > 쓸모 있는 구간 {width}분"


@pytest.mark.parametrize("workflow", ["brief-kr.yml", "brief-us.yml"])
def test_waiting_fits_in_the_job_timeout(workflow):
    """기다림 + 생성이 잡 한도 안이어야 한다 — 넘으면 창 직전에 잡이 죽는다."""
    job = yaml.safe_load((WORKFLOWS / workflow).read_text(encoding="utf-8"))["jobs"]["brief"]
    timeout = job.get("timeout-minutes", 360)
    assert BRIEF_MAX_WAIT_MIN + 30 <= timeout <= 360


def test_close_brief_covers_every_delay_up_to_4h():
    """장 마감 브리핑 — 첫 슬롯이 240분 밀려도 마감 브리핑 창(15:40~20:30 KST) 안이어야 한다."""
    start, end = CLOSE_BRIEF_WINDOW["KR"]
    assert_full_coverage(slots_utc("brief-kr-close.yml"), band_utc(start, end, UTC_OFFSET["KR"]),
                         "brief-kr-close", max_delay=CLOSE_MAX_DELAY_MIN)


def test_close_brief_never_wakes_before_the_close():
    """15:30 마감 전에 깨어난 슬롯은 장중 값으로 판정한다 — 게이트가 막지만 슬롯부터 뒤에 둔다."""
    first = min(slots_utc("brief-kr-close.yml")) + UTC_OFFSET["KR"] * 60
    assert first >= _minutes(CLOSE_BRIEF_WINDOW["KR"][0])


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


# --------------------------------------------------------------------------
# 슬롯이 아예 안 깨는 날 — 2026-11-03
# --------------------------------------------------------------------------
# 위 커버리지 테스트는 "슬롯이 늦게라도 전부 깬다"를 가정한다. 그날 GitHub 은 예약 실행을
# 5~10시간 밀고 대부분 버렸다. 미장 브리핑 슬롯은 하루 12개 중 2개만 깼고, 09:25Z~14:40Z
# 에는 어떤 워크플로도 깨지 않았다. 아래는 실제로 깬 예약 실행이 창 시작 몇 분 전이었나
# (음수 = 창 시작 뒤). 국장 창 시작 = 11-02 22:45Z, 미장 창 시작 = 11-03 13:15Z(EST).
WOKE_2026_11_03 = {
    "KR": {"brief": [-127],
           # data-sync · brief-kr-close · pulse 가 11-02 17:25Z~19:46Z 에 깼다
           "others": [319, 318, 292, 272, 259, 235, 233, 195, 184, 178]},
    "US": {"brief": [283],
           # pulse 07:37Z, brief-kr 09:24Z
           "others": [337, 230]},
}
OLD_MAX_WAIT_MIN = 240   # 그날 쓰던 값


def _on_time(woke: list[int], max_wait: int) -> list[int]:
    return [m for m in woke if 0 <= m <= max_wait]


@pytest.mark.parametrize("market", ["KR", "US"])
def test_2026_11_03_brief_slots_alone_missed(market):
    """그날 브리핑 자기 슬롯은 둘 다 정시 발송으로 못 이어졌다 — 국장 09:54 KST 지각,
    미장은 283분 전에 깬 슬롯이 대기 한도 240분에 걸려 그냥 끝났다."""
    assert not _on_time(WOKE_2026_11_03[market]["brief"], OLD_MAX_WAIT_MIN)


@pytest.mark.parametrize("market", ["KR", "US"])
def test_2026_11_03_is_rescued_by_other_workflows(market):
    """다른 워크플로가 깬 김에 불러 주면(kick-briefs.sh) 둘 다 정시였다.
    대기 한도를 올리지 않아도 이 경로만으로 둘 다 구해진다."""
    others = WOKE_2026_11_03[market]["others"]
    assert _on_time(others, OLD_MAX_WAIT_MIN)
    assert _on_time(others + WOKE_2026_11_03[market]["brief"], BRIEF_MAX_WAIT_MIN)


@pytest.mark.parametrize("workflow", ["brief-kr.yml", "brief-us.yml"])
def test_brief_slots_run_every_day(workflow):
    """장전 브리핑 슬롯은 매일 돈다 — 주말·휴장일은 gate 가 현지 날짜로 거른다.
    UTC 요일로 거르면 자정을 넘겨 깨는 슬롯(국장은 전날 UTC)이 엉뚱한 날에 빠진다."""
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    specs = set(re.findall(r'-\s*cron:\s*"\d+\s+\S+\s+\*\s+\*\s+(\S+)"', text))
    assert specs == {"*"}, f"{workflow}: 요일 지정이 {specs}"
