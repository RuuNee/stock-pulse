"""시세 소스가 뒤로 갈 때 데이터를 잃지 않는지 고정한다.

2026-08-04 실제 사고 (AAPL):
    08-03 22:58 UTC (18:58 ET)  quote 2026-08-03  ← 정상
    08-04 10:30 UTC (06:30 ET)  quote 2026-07-31  ← 08-03 을 잃음
이른 아침 ET 구간에서 소스가 전날 일봉을 잠깐 내렸고, 그대로 덮어써서
미장이 화면상 나흘 멈춰 보였다.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from pipeline.build import site_data
from pipeline.collect import prices


META = {"market": "US", "code": "AAPL", "name": "Apple"}


def frame(days: list[str], closes: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {"Open": closes, "High": closes, "Low": closes,
         "Close": closes, "Volume": [1000.0] * len(days)},
        index=pd.to_datetime(days),
    )


@pytest.fixture
def stored(tmp_path, monkeypatch):
    """`data/tickers/US/AAPL.json` 이 08-03 까지 들어 있는 상태."""
    monkeypatch.setattr(site_data, "DATA_DIR", tmp_path)
    path = tmp_path / "tickers" / "US" / "AAPL.json"
    path.parent.mkdir(parents=True)
    df = frame(["2026-07-31", "2026-08-03"], [308.91, 303.42])
    path.write_text(json.dumps({
        "quote": {"date": "2026-08-03", "close": 303.42},
        "ohlcv": {"columns": ["d", "o", "h", "l", "c", "v"], "rows": prices.to_rows(df)},
    }), encoding="utf-8")
    return tmp_path


def test_backslide_restores_stored_bars(stored):
    """소스가 07-31 까지만 주면 저장된 08-03 을 지킨다."""
    regressed = frame(["2026-07-31"], [308.91])

    out = site_data._no_backslide(META, regressed)

    assert out.index[-1].strftime("%Y-%m-%d") == "2026-08-03"
    assert float(out["Close"].iloc[-1]) == pytest.approx(303.42)


def test_newer_data_passes_through(stored):
    fresh = frame(["2026-07-31", "2026-08-03", "2026-08-04"], [308.91, 303.42, 310.0])

    out = site_data._no_backslide(META, fresh)

    assert out.index[-1].strftime("%Y-%m-%d") == "2026-08-04"


def test_same_day_rebuild_passes_through(stored):
    """같은 날 다시 돌린 경우는 통과시킨다 — 종가가 정정될 수 있다."""
    same = frame(["2026-07-31", "2026-08-03"], [308.91, 304.0])

    out = site_data._no_backslide(META, same)

    assert float(out["Close"].iloc[-1]) == pytest.approx(304.0)


def test_no_stored_file_passes_through(tmp_path, monkeypatch):
    monkeypatch.setattr(site_data, "DATA_DIR", tmp_path)
    fresh = frame(["2026-08-03"], [303.42])

    assert site_data._no_backslide(META, fresh) is fresh


def test_empty_stored_rows_pass_through(tmp_path, monkeypatch):
    """저장본이 비어 있으면 되돌릴 게 없다 — 새 데이터를 쓴다."""
    monkeypatch.setattr(site_data, "DATA_DIR", tmp_path)
    path = tmp_path / "tickers" / "US" / "AAPL.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"quote": {"date": "2026-08-03"}, "ohlcv": {"rows": []}}),
                    encoding="utf-8")
    fresh = frame(["2026-07-31"], [308.91])

    assert site_data._no_backslide(META, fresh) is fresh


def test_from_rows_roundtrip():
    df = frame(["2026-07-31", "2026-08-03"], [308.91, 303.42])

    back = prices.from_rows(prices.to_rows(df))

    assert list(back.index.strftime("%Y-%m-%d")) == ["2026-07-31", "2026-08-03"]
    assert float(back["Close"].iloc[-1]) == pytest.approx(303.42)
