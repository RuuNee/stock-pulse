"""실적 캘린더 — 브리핑에서 유일하게 앞을 보는 블록.

네트워크는 타지 않는다. 외부 응답을 정규화하는 부분과, 캘린더가 죽어도
브리핑은 나가야 한다는 계약만 고정한다.
"""

from __future__ import annotations

from datetime import date

import pytest

from pipeline.build import brief
from pipeline.collect import calendar as calendar_mod
from pipeline.config import CALENDAR_MAX_ITEMS, CALENDAR_MIN_MARCAP


def _row(symbol="WMT", name="Walmart Inc.", cap="$916,770,718,656",
         when="time-pre-market", eps="$0.73") -> dict:
    return {"symbol": symbol, "name": name, "marketCap": cap,
            "time": when, "epsForecast": eps}


# --------------------------------------------------------------------------
# 정규화
# --------------------------------------------------------------------------

def test_normalize_parses_money_and_timing():
    got = calendar_mod._normalize(_row(), date(2026, 8, 20))
    assert got["code"] == "WMT"
    assert got["marcap"] == 916_770_718_656
    assert got["when"] == "개장 전"
    assert got["epsForecast"] == "$0.73"
    assert got["date"] == "2026-08-20"


@pytest.mark.parametrize("raw,expected", [
    ("time-pre-market", "개장 전"),
    ("time-after-hours", "장 마감 후"),
    ("time-not-supplied", "시간 미정"),
    (None, "시간 미정"),
])
def test_timing_labels(raw, expected):
    assert calendar_mod._when(raw) == expected


def test_small_caps_are_dropped():
    """실적 시즌엔 하루 100건 가까이 나온다. 스몰캡까지 실으면 브리핑이 노이즈가 된다."""
    tiny = _row(symbol="TINY", cap="$1,000,000")
    assert calendar_mod._normalize(tiny, date(2026, 8, 20)) is None

    big = _row(symbol="BIG", cap=f"${CALENDAR_MIN_MARCAP:,}")
    assert calendar_mod._normalize(big, date(2026, 8, 20)) is not None


def test_missing_marcap_is_kept():
    """시총을 안 주는 종목이 있다. 모른다고 버리면 큰 발표를 놓친다."""
    got = calendar_mod._normalize(_row(cap=None), date(2026, 8, 20))
    assert got is not None and got["marcap"] is None


def test_row_without_symbol_is_dropped():
    assert calendar_mod._normalize(_row(symbol=""), date(2026, 8, 20)) is None


# --------------------------------------------------------------------------
# 브리핑 연결
# --------------------------------------------------------------------------

def test_brief_calendar_prefers_the_session_day(monkeypatch):
    session = date(2026, 8, 20)
    items = [
        {"date": "2026-08-21", "code": "LATER", "market": "US", "name": "Later Inc",
         "when": "개장 전", "epsForecast": None, "marcap": 200_000_000_000},
        {"date": "2026-08-20", "code": "TODAY", "market": "US", "name": "Today Inc",
         "when": "장 마감 후", "epsForecast": "$1.00", "marcap": 200_000_000_000},
    ]
    monkeypatch.setattr(calendar_mod, "fetch_earnings", lambda *a, **k: items)

    got = brief._calendar("KR", session)

    assert [c["code"] for c in got] == ["TODAY"], "당일 항목이 있으면 그것만 싣는다"
    assert got[0]["importance"] == "high", "시총 1000억 달러 이상은 강조한다"
    assert "실적 발표" in got[0]["title"]


def test_brief_calendar_falls_back_to_upcoming(monkeypatch):
    """당일 발표가 없으면 빈 블록 대신 다가오는 일정을 보여 준다."""
    items = [{"date": "2026-08-21", "code": "SOON", "market": "US", "name": "Soon Inc",
              "when": "개장 전", "epsForecast": None, "marcap": 10_000_000_000}]
    monkeypatch.setattr(calendar_mod, "fetch_earnings", lambda *a, **k: items)

    got = brief._calendar("KR", date(2026, 8, 20))

    assert [c["code"] for c in got] == ["SOON"]
    assert got[0]["importance"] == "normal"


def test_brief_calendar_is_capped(monkeypatch):
    items = [{"date": "2026-08-20", "code": f"T{i}", "market": "US", "name": f"N{i}",
              "when": "개장 전", "epsForecast": None, "marcap": 10_000_000_000}
             for i in range(20)]
    monkeypatch.setattr(calendar_mod, "fetch_earnings", lambda *a, **k: items)

    assert len(brief._calendar("US", date(2026, 8, 20))) == CALENDAR_MAX_ITEMS


def test_calendar_failure_does_not_break_the_brief(monkeypatch):
    """소스가 죽어도 브리핑은 나가야 한다 — 캘린더는 부가 정보다."""
    def boom(*a, **k):
        raise RuntimeError("nasdaq down")

    monkeypatch.setattr(calendar_mod, "fetch_earnings", boom)
    assert brief._calendar("KR", date(2026, 8, 20)) == []


def test_calendar_can_be_switched_off(monkeypatch):
    monkeypatch.setattr(brief, "CALENDAR_EARNINGS", False)
    monkeypatch.setattr(calendar_mod, "fetch_earnings",
                        lambda *a, **k: pytest.fail("꺼져 있으면 호출하지 않는다"))
    assert brief._calendar("KR", date(2026, 8, 20)) == []
