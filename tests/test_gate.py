"""브리핑 발송 판정 테스트.

2026-07-28 국장 브리핑이 안 나간 원인이 이 판정과 슬롯 배치의 조합이었으므로,
"창 밖이면 막는다"와 "창 안이면 보낸다"를 양쪽 다 고정해 둔다.

2026-08-07 에 같은 증상이 다시 났는데 원인은 달랐다 — 슬롯 7개가 한 덩어리로
창 뒤에 방출됐고, 판정은 옳게 전부 버렸지만 그날 브리핑이 통째로 사라졌다.
그래서 지금은 창 뒤에도 지각 마감 전이면 LATE 로 보낸다. 아래 표가 그 경계다.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from pipeline.config import ET, KST
from pipeline.gate import LATE, ON_TIME, SKIP, decide, send_mode


def kst(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=KST)


def et(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=ET)


@pytest.fixture
def empty_data(tmp_path):
    (tmp_path / "brief").mkdir()
    return tmp_path


# 2026-07-28 은 화요일 — 국장/미장 모두 정상 개장일.
@pytest.mark.parametrize("hh,mm,expected", [
    (4, 20, SKIP),      # 가장 이른 슬롯이 제시간에 깨어난 경우 — 뒤 슬롯에 맡긴다
    (7, 44, SKIP),      # 창 1분 전
    (7, 45, ON_TIME),   # 창 시작
    (8, 20, ON_TIME),   # 지연 없는 슬롯의 정상 발송 시각
    (8, 40, ON_TIME),   # 창 끝
    (8, 41, LATE),      # 창 1분 후 — 여기부터 지각 발송
    (9, 9, LATE),       # 2026-07-28 사고: 23:11Z 슬롯이 09:09 KST 에 깨어났다
    (10, 45, LATE),     # 2026-08-07 사고: 몰려서 방출된 마지막 슬롯
    (12, 0, LATE),      # 지각 마감 정각까지는 보낸다
    (12, 1, SKIP),      # 마감 1분 후 — 장전 브리핑이라기엔 너무 늦었다
])
def test_kr_send_mode(empty_data, hh, mm, expected):
    mode, reason = send_mode("KR", now=kst(2026, 7, 28, hh, mm), data_dir=empty_data)
    assert mode == expected, reason


@pytest.mark.parametrize("hh,mm,expected", [
    (4, 40, SKIP),
    (8, 14, SKIP),
    (8, 15, ON_TIME),
    (8, 40, ON_TIME),
    (9, 10, ON_TIME),
    (9, 11, LATE),
    (11, 23, LATE),     # 실제 사고: brief-us 가 173분 밀려 깨어난 시각
    (12, 30, LATE),
    (12, 31, SKIP),
])
def test_us_send_mode(empty_data, hh, mm, expected):
    mode, reason = send_mode("US", now=et(2026, 7, 28, hh, mm), data_dir=empty_data)
    assert mode == expected, reason


def test_decide_treats_a_late_slot_as_send(empty_data):
    """워크플로의 run 판정은 bool 하나다 — 지각도 '보낸다' 쪽이어야 한다."""
    run, reason = decide("KR", now=kst(2026, 7, 28, 10, 45), data_dir=empty_data)
    assert run is True, reason


def test_late_reason_says_it_is_late(empty_data):
    """운영자가 로그만 보고 정시/지각을 구분할 수 있어야 한다."""
    _, reason = send_mode("KR", now=kst(2026, 7, 28, 10, 45), data_dir=empty_data)
    assert "지각" in reason and "12:00" in reason


def test_holiday_blocks_send(empty_data):
    # 2026-08-15 광복절(토) 대신 실제 평일 휴장일인 2026-08-17(월) 대체공휴일.
    run, reason = decide("KR", now=kst(2026, 8, 17, 8, 20), data_dir=empty_data)
    assert run is False
    assert "휴장" in reason


def test_weekend_blocks_send(empty_data):
    run, _ = decide("KR", now=kst(2026, 7, 25, 8, 20), data_dir=empty_data)  # 토요일
    assert run is False


def test_existing_brief_blocks_duplicate(empty_data):
    (empty_data / "brief" / "2026-07-28-KR.json").write_text(
        json.dumps({"market": "KR"}), encoding="utf-8")
    run, reason = decide("KR", now=kst(2026, 7, 28, 8, 20), data_dir=empty_data)
    assert run is False
    assert "중복" in reason


def test_late_window_still_respects_duplicates(empty_data):
    """몰려서 깨어난 슬롯 7개가 전부 지각 발송이면 같은 브리핑이 7번 간다.
    먼저 깬 슬롯이 파일을 커밋하므로, 중복 검사가 지각 경로에서도 살아 있어야 한다."""
    (empty_data / "brief" / "2026-07-28-KR.json").write_text("{}", encoding="utf-8")
    mode, reason = send_mode("KR", now=kst(2026, 7, 28, 10, 45), data_dir=empty_data)
    assert mode == SKIP and "중복" in reason


def test_late_window_still_respects_holidays(empty_data):
    mode, _ = send_mode("KR", now=kst(2026, 8, 17, 10, 45), data_dir=empty_data)
    assert mode == SKIP


def test_force_reports_on_time(empty_data):
    """수동 실행은 창과 무관하다 — '늦은 브리핑' 딱지가 붙으면 안 된다."""
    mode, _ = send_mode("KR", now=kst(2026, 7, 28, 14, 0), force=True, data_dir=empty_data)
    assert mode == ON_TIME


def test_force_overrides_everything(empty_data):
    (empty_data / "brief" / "2026-07-28-KR.json").write_text("{}", encoding="utf-8")
    run, _ = decide("KR", now=kst(2026, 7, 28, 3, 0), force=True, data_dir=empty_data)
    assert run is True


def test_unknown_market_raises(empty_data):
    with pytest.raises(ValueError):
        send_mode("JP", now=kst(2026, 7, 28, 8, 20), data_dir=empty_data)
