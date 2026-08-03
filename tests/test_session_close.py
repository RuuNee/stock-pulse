"""장중 미완성 봉을 종가로 싣지 않는지 고정한다.

2026-08-03 실제 신고: 사이트가 "마감 기준"이라고 써 놓고 지수는 2시간마다
달라지는 값을 보여줬다. 원인은 시세 소스가 장중에도 "오늘" 행을 준다는 것.
미장 개장 18분 만에 이미 그날 봉이 나왔다(US500 close=7543.19, 확정 종가 아님).
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import pytest

from pipeline.collect.prices import drop_unclosed
from pipeline.config import ET, KST
from pipeline.util.dates import session_closed


def frame(days: list[str]) -> pd.DataFrame:
    idx = pd.to_datetime(days)
    return pd.DataFrame(
        {"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": 1.0, "Volume": 1.0},
        index=idx,
    )


# --------------------------------------------------------------- session_closed
@pytest.mark.parametrize("hh,mm,expected", [
    (9, 30, False),   # 개장 직후 — 진행 중
    (15, 29, False),  # 마감 1분 전
    (15, 30, True),   # 마감 시각
    (18, 0, True),    # 마감 후
])
def test_kr_close_boundary(hh, mm, expected):
    now = datetime(2026, 8, 3, hh, mm, tzinfo=KST)
    assert session_closed("KR", date(2026, 8, 3), now) is expected


@pytest.mark.parametrize("hh,mm,expected", [
    (9, 48, False),   # 실제 사고 시각 — 소스는 이미 오늘 봉을 주고 있었다
    (15, 59, False),
    (16, 0, True),
    (17, 30, True),   # data-sync 정기 실행 시각(21:30 UTC)
])
def test_us_close_boundary(hh, mm, expected):
    now = datetime(2026, 8, 3, hh, mm, tzinfo=ET)
    assert session_closed("US", date(2026, 8, 3), now) is expected


def test_past_day_is_always_closed():
    now = datetime(2026, 8, 3, 9, 48, tzinfo=ET)
    assert session_closed("US", date(2026, 7, 31), now) is True


def test_future_day_is_never_closed():
    now = datetime(2026, 8, 3, 18, 0, tzinfo=ET)
    assert session_closed("US", date(2026, 8, 4), now) is False


def test_global_follows_us_clock():
    """GLOBAL(유가·금·달러인덱스)은 미국 종료를 기준으로 삼는다."""
    open_et = datetime(2026, 8, 3, 10, 0, tzinfo=ET)
    assert session_closed("GLOBAL", date(2026, 8, 3), open_et) is False
    assert session_closed("GLOBAL", date(2026, 8, 3),
                          datetime(2026, 8, 3, 16, 0, tzinfo=ET)) is True


# ---------------------------------------------------------------- drop_unclosed
def test_drops_only_the_unclosed_bar(monkeypatch):
    df = frame(["2026-07-30", "2026-07-31", "2026-08-03"])
    monkeypatch.setattr("pipeline.collect.prices.session_closed",
                        lambda market, day: day < date(2026, 8, 3))

    out = drop_unclosed(df, "US")

    assert len(out) == 2
    assert out.index[-1].date() == date(2026, 7, 31)


def test_keeps_frame_when_session_is_over(monkeypatch):
    df = frame(["2026-07-31", "2026-08-03"])
    monkeypatch.setattr("pipeline.collect.prices.session_closed",
                        lambda market, day: True)

    assert len(drop_unclosed(df, "US")) == 2


def test_single_unclosed_bar_becomes_none(monkeypatch):
    """한 줄뿐인데 그게 진행 중이면 빈 프레임 대신 None — 호출부가 skip 한다."""
    monkeypatch.setattr("pipeline.collect.prices.session_closed",
                        lambda market, day: False)

    assert drop_unclosed(frame(["2026-08-03"]), "US") is None


def test_empty_input_passes_through():
    assert drop_unclosed(None, "US") is None
