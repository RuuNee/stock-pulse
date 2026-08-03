"""차트 분석 판정기 — 계산이 아니라 **계약**을 지킨다.

지표 숫자 자체를 검증하지는 않는다 (pandas 가 이미 검증된 코드다). 대신 이
모듈이 깨졌을 때 실제로 사이트가 망가지는 지점만 고정한다.

  1. 출력이 JSON 으로 나가는가 — 스키마 §7 은 NaN/Infinity 를 금지한다.
     여기서 새는 순간 웹 전체가 파싱 실패로 흰 화면이 된다.
  2. 지표 배열 길이가 ohlcv.rows 와 같은가 — 어긋나면 차트에 선이 밀려 그려진다.
  3. 교과서 신호가 교과서대로 나오는가 — 골든크로스 차트에서 골든크로스가 뜨는가.
  4. 이상한 입력에 죽지 않는가 — 값이 한 번도 안 변하는 종목, 거래량 0인 계열.
     (얇은 ETF 의 14일 무변동 구간이 실제로 스토캐스틱을 죽인 적이 있다)
"""

from __future__ import annotations

import json
import math

import pandas as pd
import pytest

from pipeline import config
from pipeline.analyze import technical


# --------------------------------------------------------------------------
# 합성 차트
# --------------------------------------------------------------------------
def wobble(i: int, amp: float = 1.0) -> float:
    """난수 대신 결정론적 잔물결 — 테스트가 실행마다 달라지면 안 된다."""
    return (math.sin(i * 1.7) * 0.6 + math.cos(i * 0.9) * 0.4) * amp


def frame(closes: list[float], *, volume: float | list[float] = 100_000.0) -> pd.DataFrame:
    idx = pd.bdate_range("2024-01-01", periods=len(closes))
    vols = volume if isinstance(volume, list) else [volume] * len(closes)
    return pd.DataFrame(
        {
            "Open": [c * 0.998 for c in closes],
            "High": [c * 1.006 for c in closes],
            "Low": [c * 0.994 for c in closes],
            "Close": closes,
            "Volume": vols,
        },
        index=idx,
    )


def v_shape(n: int = 200, low_at: float = 0.5) -> list[float]:
    """내려갔다 올라오는 차트 → 20일선이 60일선을 위로 뚫는다."""
    turn = int(n * low_at)
    return [
        (150 - i * 0.7 if i < turn else 150 - turn * 0.7 + (i - turn) * 0.9) + wobble(i, 1.5)
        for i in range(n)
    ]


def n_shape(n: int = 200) -> list[float]:
    return [180 - c for c in v_shape(n)]


# 직선으로 오르내리기만 하는 차트는 만들지 않는다 — 내린 날이 하나도 없으면
# RSI 가 85 에 박혀 "과매수(약세)"로 굳고, 추세 신호와 상쇄돼 점수가 0 이 된다.
# 실제 차트에는 늘 조정이 섞여 있으므로 파도를 얹어 그 모양에 맞춘다.
UP = [100 + i * 0.6 + math.sin(i / 6) * 6 + wobble(i, 2) for i in range(200)]
# 위아래로 뒤집기만 한다. 그러면 이동평균 순서도 정확히 뒤집히므로, 마지막 봉이
# 우연히 단기 반등 구간에 걸려 배열 판정이 흐려지는 일이 없다.
DOWN = [360 - c for c in UP]


# --------------------------------------------------------------------------
# 1. JSON 계약
# --------------------------------------------------------------------------
@pytest.mark.parametrize("closes", [UP, DOWN, v_shape(), n_shape()])
def test_output_is_json_safe(closes):
    """allow_nan=False 로 직렬화된다 = NaN/Infinity 가 하나도 없다."""
    df = frame(closes)
    json.dumps(technical.analyze(df), ensure_ascii=False, allow_nan=False)
    json.dumps(technical.series(df), allow_nan=False)


def test_series_length_matches_rows():
    df = frame(UP)
    for key, values in technical.series(df).items():
        assert len(values) == len(df), f"{key}: 길이가 ohlcv.rows 와 다르다"


def test_analysis_has_every_field_the_web_reads():
    """web/src/lib/types.ts 의 TickerAnalysis 와 맞물리는 최소 집합."""
    a = technical.analyze(frame(UP))
    for key in ("date", "score", "signal", "label", "action", "actionEmoji",
                "actionLabel", "actionNote", "headline", "summary", "trend",
                "counts", "signals", "levels", "risk", "disclaimer"):
        assert key in a, f"analysis 에 {key} 가 없다"
    assert a["signal"] in technical.SIGNAL_LABELS
    assert a["action"] in technical.ACTIONS
    for sig in a["signals"]:
        assert sig["verdict"] in ("bullish", "bearish", "neutral")
        assert 0.0 <= sig["strength"] <= 1.0
        assert sig["weight"] >= 1


# --------------------------------------------------------------------------
# 2. 교과서 신호
# --------------------------------------------------------------------------
def signal_by_key(analysis: dict, key: str) -> dict | None:
    return next((s for s in analysis["signals"] if s["key"] == key), None)


def test_golden_cross_on_a_v_shaped_chart():
    """바닥을 찍고 올라온 직후에는 골든크로스가 잡혀야 한다.

    반등 시작에서 딱 `TA_CROSS_LOOKBACK` 거래일 뒤를 마지막 봉으로 잘라, 교차가
    '최근'에 들어오게 만든다.
    """
    closes = v_shape(400, low_at=0.5)
    turn = 200
    # 바닥에서 20일선이 60일선을 다시 넘기까지 20~30거래일쯤 걸리는데, 정확히
    # 며칠인지는 파형에 달렸다. 마지막 봉을 하루씩 늦춰 가며 교차가 "최근
    # TA_CROSS_LOOKBACK 거래일" 창에 들어오는 순간을 찾는다.
    found = None
    for end in range(turn + 5, turn + 150):
        cross = signal_by_key(technical.analyze(frame(closes[:end])), "maCross")
        if cross and cross["name"] == "골든크로스 발생":
            found = cross
            break
    assert found is not None, "V자 반등 차트에서 골든크로스를 못 찾았다"
    assert found["verdict"] == "bullish"


def test_dead_cross_on_an_n_shaped_chart():
    closes = n_shape(400)
    turn = 200
    found = None
    for end in range(turn + 5, turn + 150):
        cross = signal_by_key(technical.analyze(frame(closes[:end])), "maCross")
        if cross and cross["name"] == "데드크로스 발생":
            found = cross
            break
    assert found is not None, "N자 하락 차트에서 데드크로스를 못 찾았다"
    assert found["verdict"] == "bearish"


def test_uptrend_scores_positive_and_downtrend_negative():
    assert technical.analyze(frame(UP))["score"] > 0
    assert technical.analyze(frame(DOWN))["score"] < 0


def test_alignment_matches_the_moving_averages():
    up = signal_by_key(technical.analyze(frame(UP)), "maAlign")
    down = signal_by_key(technical.analyze(frame(DOWN)), "maAlign")
    assert up["name"] == "이동평균 정배열" and up["verdict"] == "bullish"
    assert down["name"] == "이동평균 역배열" and down["verdict"] == "bearish"


def test_breakout_fires_at_a_new_high():
    """마지막 봉만 크게 띄우면 60일 신고가 돌파가 떠야 한다."""
    closes = [130 + wobble(i, 2) for i in range(200)]
    closes[-1] = 200.0
    breakout = signal_by_key(technical.analyze(frame(closes)), "breakout")
    assert breakout["verdict"] == "bullish"
    assert "신고가" in breakout["name"]


# --------------------------------------------------------------------------
# 3. 점수 → 라벨 구간
# --------------------------------------------------------------------------
@pytest.mark.parametrize("score,expected", [
    (100, "strongBuy"), (45, "strongBuy"), (44, "buy"), (15, "buy"),
    (14, "neutral"), (0, "neutral"), (-15, "neutral"),
    (-16, "sell"), (-45, "sell"), (-46, "strongSell"), (-100, "strongSell"),
])
def test_score_bands(score, expected):
    assert technical._band(score) == expected


def test_every_band_has_a_label():
    for _, key in config.TA_SIGNAL_BANDS:
        assert key in technical.SIGNAL_LABELS
    assert "strongSell" in technical.SIGNAL_LABELS  # 마지막 폴백


# --------------------------------------------------------------------------
# 4. 험한 입력
# --------------------------------------------------------------------------
def test_too_short_history_returns_none():
    assert technical.analyze(frame([100.0 + i for i in range(config.TA_MIN_BARS - 1)])) is None
    assert technical.analyze(None) is None


def test_flat_prices_do_not_crash():
    """값이 한 번도 안 변하는 구간 — 스토캐스틱 분모가 0이 된다.

    2026-08-02 에 얇은 ETF 가 정확히 이걸로 파이프라인을 죽였다
    (pandas: "No numeric types to aggregate").
    """
    a = technical.analyze(frame([100.0] * 200))
    json.dumps(a, ensure_ascii=False, allow_nan=False)
    assert a["signal"] == "neutral"


def test_zero_volume_series_skip_the_volume_check():
    """지수·환율처럼 거래량이 없는 계열도 분석은 나와야 한다."""
    a = technical.analyze(frame(UP, volume=0.0))
    assert signal_by_key(a, "volume") is None
    assert a["score"] != 0
    json.dumps(a, ensure_ascii=False, allow_nan=False)


def test_brief_entry_is_none_without_analysis():
    assert technical.brief_entry({"analysis": None}) is None
    assert technical.brief_entry({}) is None


def test_brief_entry_shape():
    entry = technical.brief_entry({"analysis": technical.analyze(frame(UP))})
    assert set(entry) == {"score", "signal", "label", "action", "actionEmoji",
                          "actionLabel", "headline", "date"}
    json.dumps(entry, ensure_ascii=False, allow_nan=False)
