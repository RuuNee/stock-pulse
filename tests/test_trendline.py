"""추세선 · 52주 위치 테스트.

추세선에서 실제로 어려운 건 "선을 긋는 것"이 아니라 **긋지 않는 것**이다.
아무 두 점이나 이으면 늘 선이 나오지만, 사람이 차트에 그어 보는 선과 다르면
근거로 못 쓴다. 그래서 버려야 하는 경우를 주로 고정한다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from pipeline.analyze.technical import _range52, _trendlines
from pipeline.config import TA_TREND_BREAK_GRACE, TA_TREND_LOOKBACK


def frame(closes: list[float], *, highs=None, lows=None) -> pd.DataFrame:
    n = len(closes)
    idx = pd.bdate_range("2026-01-05", periods=n)
    c = np.array(closes, dtype=float)
    return pd.DataFrame(
        {
            "Open": c,
            "High": np.array(highs, dtype=float) if highs is not None else c * 1.01,
            "Low": np.array(lows, dtype=float) if lows is not None else c * 0.99,
            "Close": c,
            "Volume": np.full(n, 1000.0),
        },
        index=idx,
    )


def zigzag(base: float, drift: float, n: int, amp: float, period: int = 20) -> list[float]:
    """추세 + 규칙적인 출렁임 — 스윙 고·저점이 생기게 만든다."""
    return [base + drift * i + amp * np.sin(2 * np.pi * i / period) for i in range(n)]


# ------------------------------------------------------------------ 추세선
def test_rising_lows_make_an_up_trendline():
    df = frame(zigzag(100, 0.5, TA_TREND_LOOKBACK, 4))
    out = _trendlines(df, float(df["Close"].iloc[-1]))

    assert out["up"] is not None
    assert out["up"]["slopePerDay"] > 0
    assert out["up"]["to"]["date"] > out["up"]["from"]["date"]


def test_falling_highs_make_a_down_trendline():
    df = frame(zigzag(200, -0.5, TA_TREND_LOOKBACK, 4))
    out = _trendlines(df, float(df["Close"].iloc[-1]))

    assert out["down"] is not None
    assert out["down"]["slopePerDay"] < 0


def test_no_line_when_direction_does_not_qualify():
    """저점이 내려가고 있으면 상승추세선을 억지로 만들지 않는다."""
    df = frame(zigzag(200, -0.8, TA_TREND_LOOKBACK, 4))

    assert _trendlines(df, float(df["Close"].iloc[-1]))["up"] is None


def test_short_frame_yields_nothing():
    df = frame([100.0] * 10)
    assert _trendlines(df, 100.0) == {"up": None, "down": None}


def test_projection_is_capped_to_the_line_span():
    """오래된 두 점을 오늘까지 늘이지 않는다.

    실제 사고: 삼성전자의 2~3월 고점 두 개(20봉 간격)가 8월까지 93봉 연장돼
    현재가 대비 -58% 인 "저항선"으로 나왔다.
    """
    n = TA_TREND_LOOKBACK
    # 앞 30봉만 출렁이고 나머지는 평평 — 스윙 점이 전부 앞쪽에만 생긴다.
    closes = zigzag(100, -1.0, 30, 5) + [60.0] * (n - 30)
    df = frame(closes)

    out = _trendlines(df, 60.0)

    for line in out.values():
        if line is None:
            continue
        # 연장했더라도 오늘 값이 현재가에서 터무니없이 떨어져 있으면 안 된다.
        assert abs(line["gapPct"]) < 100


def test_line_broken_long_ago_is_dropped():
    """깬 뒤 오래 반대편에 머물면 죽은 선이다."""
    n = TA_TREND_LOOKBACK
    rising = zigzag(100, 0.6, n - TA_TREND_BREAK_GRACE * 3, 4)
    crashed = [rising[-1] * 0.5] * (TA_TREND_BREAK_GRACE * 3)
    df = frame(rising + crashed)

    assert _trendlines(df, float(df["Close"].iloc[-1]))["up"] is None


def test_fresh_break_keeps_the_line():
    """방금 깬 건 살려 둔다 — 그게 우리가 알리려는 신호다."""
    n = TA_TREND_LOOKBACK
    rising = zigzag(100, 0.6, n - 2, 4)
    df = frame(rising + [rising[-1] * 0.93, rising[-1] * 0.92])

    up = _trendlines(df, float(df["Close"].iloc[-1]))["up"]

    assert up is not None
    assert up["gapPct"] < 0   # 선 아래 = 이탈


# -------------------------------------------------------------- 52주 위치
def test_range52_positions():
    df = frame(list(np.linspace(100, 200, 260)))
    price = 150.0

    out = _range52(df, price)

    assert out["high52Pct"] < 0     # 고점보다 아래
    assert out["low52Pct"] > 0      # 저점보다 위
    assert 0 <= out["rangePos"] <= 100


def test_range52_at_the_top():
    df = frame(list(np.linspace(100, 200, 260)))
    out = _range52(df, float(df["High"].max()))

    assert out["rangePos"] == pytest.approx(100, abs=0.5)


def test_range52_flat_series_has_no_position():
    """고점과 저점이 같으면 '몇 % 지점'이라는 말 자체가 성립하지 않는다."""
    df = frame([100.0] * 260, highs=[100.0] * 260, lows=[100.0] * 260)

    assert _range52(df, 100.0)["rangePos"] is None
