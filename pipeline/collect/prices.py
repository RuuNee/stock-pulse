"""Daily OHLCV collection via FinanceDataReader.

One API covers KOSPI/KOSDAQ, NYSE/NASDAQ, indices, FX and commodities — see
md파일/01-데이터소스.md for the verification table.
"""

from __future__ import annotations

import time
from datetime import date, timedelta

import pandas as pd

from ..config import HISTORY_YEARS
from ..util import log

_COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def _fdr():
    import FinanceDataReader as fdr  # imported lazily: it is slow to load
    return fdr


def fetch_ohlcv(symbol: str, *, years: int = HISTORY_YEARS,
                retries: int = 2) -> pd.DataFrame | None:
    """Return a normalised OHLCV frame, or None when the symbol is unavailable."""
    start = (date.today() - timedelta(days=int(365.25 * years) + 10)).isoformat()
    last_error: Exception | None = None

    for attempt in range(retries + 1):
        try:
            df = _fdr().DataReader(symbol, start)
        except Exception as exc:
            last_error = exc
            time.sleep(1.0 + attempt)
            continue

        if df is None or df.empty:
            last_error = ValueError("empty frame")
            time.sleep(1.0 + attempt)
            continue

        return _normalize(df)

    log.warn(f"price fetch failed: {symbol} ({last_error})")
    return None


def _normalize(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.index = pd.to_datetime(df.index)
    df = df[~df.index.duplicated(keep="last")].sort_index()

    for col in _COLUMNS:
        if col not in df.columns:
            # Indices and FX series often have no volume.
            df[col] = df["Close"] if col != "Volume" else 0.0
    df = df[_COLUMNS]

    # A zero close is a data glitch, not a real price.
    df = df[df["Close"] > 0]
    df[_COLUMNS] = df[_COLUMNS].apply(pd.to_numeric, errors="coerce")
    return df.dropna(subset=["Close"])


def to_rows(df: pd.DataFrame) -> list[list]:
    """Compact array-of-arrays form used by the site (schema §4)."""
    rows: list[list] = []
    for ts, r in df.iterrows():
        rows.append([
            ts.strftime("%Y-%m-%d"),
            _num(r["Open"]), _num(r["High"]), _num(r["Low"]), _num(r["Close"]),
            int(r["Volume"]) if pd.notna(r["Volume"]) else 0,
        ])
    return rows


def _num(value) -> float | None:
    if pd.isna(value):
        return None
    value = float(value)
    # Korean prices are whole won; US prices need cents.
    return round(value, 4)


def quote_from(df: pd.DataFrame) -> dict:
    """Latest bar plus the derived numbers the UI shows above the chart."""
    if df is None or df.empty:
        return {}
    last = df.iloc[-1]
    prev_close = float(df["Close"].iloc[-2]) if len(df) >= 2 else float(last["Close"])
    close = float(last["Close"])
    change = close - prev_close
    window = df.tail(252)
    vol_ma20 = float(df["Volume"].tail(20).mean() or 0)

    return {
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "open": _num(last["Open"]),
        "high": _num(last["High"]),
        "low": _num(last["Low"]),
        "close": _num(close),
        "prevClose": _num(prev_close),
        "change": _num(change),
        "changePct": round(change / prev_close * 100, 2) if prev_close else None,
        "volume": int(last["Volume"]) if pd.notna(last["Volume"]) else 0,
        "volumeVsAvg20": round(float(last["Volume"]) / vol_ma20, 2) if vol_ma20 else None,
        "high52": _num(window["High"].max()),
        "low52": _num(window["Low"].min()),
    }


def spark(df: pd.DataFrame, points: int = 30) -> list[float]:
    if df is None or df.empty:
        return []
    return [round(float(v), 4) for v in df["Close"].tail(points).tolist()]
