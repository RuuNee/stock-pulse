"""브리핑 발송 판정 테스트.

2026-07-28 국장 브리핑이 안 나간 원인이 이 판정과 슬롯 배치의 조합이었으므로,
"창 밖이면 막는다"와 "창 안이면 보낸다"를 양쪽 다 고정해 둔다.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from pipeline.config import ET, KST
from pipeline.gate import decide


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
    (4, 20, False),   # 가장 이른 슬롯이 제시간에 깨어난 경우
    (7, 44, False),   # 창 1분 전
    (7, 45, True),    # 창 시작
    (8, 20, True),    # 지연 없는 슬롯의 정상 발송 시각
    (8, 40, True),    # 창 끝
    (8, 41, False),   # 창 1분 후
    (9, 9, False),    # 실제 사고: 23:11Z 슬롯이 09:09 KST 에 깨어났다
])
def test_kr_window(empty_data, hh, mm, expected):
    run, reason = decide("KR", now=kst(2026, 7, 28, hh, mm), data_dir=empty_data)
    assert run is expected, reason


@pytest.mark.parametrize("hh,mm,expected", [
    (4, 40, False),
    (8, 14, False),
    (8, 15, True),
    (8, 40, True),
    (9, 10, True),
    (9, 11, False),
    (11, 23, False),  # 실제 사고: brief-us 가 173분 밀려 깨어난 시각
])
def test_us_window(empty_data, hh, mm, expected):
    run, reason = decide("US", now=et(2026, 7, 28, hh, mm), data_dir=empty_data)
    assert run is expected, reason


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


def test_force_overrides_everything(empty_data):
    (empty_data / "brief" / "2026-07-28-KR.json").write_text("{}", encoding="utf-8")
    run, _ = decide("KR", now=kst(2026, 7, 28, 3, 0), force=True, data_dir=empty_data)
    assert run is True


def test_unknown_market_raises(empty_data):
    with pytest.raises(ValueError):
        decide("JP", now=kst(2026, 7, 28, 8, 20), data_dir=empty_data)
