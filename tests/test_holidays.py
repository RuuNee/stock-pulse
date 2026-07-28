"""휴장일 표가 해를 넘길 때의 동작.

표는 2026년만 손으로 채워져 있다. 해가 바뀌면 표가 없는 상태가 되는데, 그때
**발송을 멈추는 것보다 흘려보내는 쪽**을 택했다 — 표가 없다고 막으면 그 해 브리핑이
통째로 사라지고, 흘려보내면 공휴일에 몇 번 더 나갈 뿐이다. 대신 조용히 틀리면 안 되므로
`doctor` 가 커버 범위를 점검한다. 그 두 성질을 여기서 고정한다.
"""

from __future__ import annotations

from datetime import date

import pytest

from pipeline.util import dates


def test_known_holidays_are_not_trading_days():
    assert dates.is_trading_day("KR", date(2026, 10, 9)) is False   # 한글날 (금)
    assert dates.is_trading_day("US", date(2026, 11, 26)) is False  # Thanksgiving (목)


def test_weekends_are_never_trading_days():
    assert dates.is_trading_day("KR", date(2026, 7, 25)) is False   # 토
    assert dates.is_trading_day("US", date(2026, 7, 26)) is False   # 일


def test_ordinary_weekday_is_a_trading_day():
    assert dates.is_trading_day("KR", date(2026, 7, 28)) is True    # 화


def test_uncovered_year_falls_through_to_weekday_only(monkeypatch):
    """표가 없는 해는 평일이면 개장으로 본다 — 발송이 멈추는 것보다 낫다."""
    monkeypatch.setitem(dates.HOLIDAYS, "KR", {2026: dates.KR_HOLIDAYS_2026})
    assert dates.is_trading_day("KR", date(2027, 1, 1)) is True     # 신정(금)인데 표가 없다
    assert dates.is_trading_day("KR", date(2027, 1, 2)) is False    # 토요일은 여전히 막힌다


def test_coverage_gap_is_empty_while_this_year_is_covered():
    """2026년을 사는 동안 KR/US 모두 최소한 올해는 덮여 있어야 한다."""
    for market in ("KR", "US"):
        assert dates.HOLIDAYS[market], f"{market}: 표가 비어 있습니다"


@pytest.mark.parametrize("market", ["KR", "US"])
def test_coverage_gap_reports_missing_years(market, monkeypatch):
    monkeypatch.setitem(dates.HOLIDAYS, market, {2026: set()})
    gap = dates.holiday_coverage_gap(market, through=date(2028, 1, 1))
    assert 2027 in gap and 2028 in gap and 2026 not in gap


@pytest.mark.parametrize("market", ["KR", "US"])
def test_coverage_gap_empty_when_all_years_present(market, monkeypatch):
    monkeypatch.setitem(dates.HOLIDAYS, market, {2026: set(), 2027: set(), 2028: set()})
    assert dates.holiday_coverage_gap(market, through=date(2028, 6, 1)) == []


def test_gate_skips_a_holiday_that_is_in_the_table(tmp_path):
    """게이트까지 이어지는지 — 표에 있는 휴장일이면 발송하지 않는다."""
    from datetime import datetime

    from pipeline.config import KST
    from pipeline.gate import decide

    (tmp_path / "brief").mkdir()
    run, reason = decide("KR", now=datetime(2026, 10, 9, 8, 20, tzinfo=KST), data_dir=tmp_path)
    assert run is False
    assert "휴장" in reason
