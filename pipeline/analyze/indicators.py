"""Technical indicators aligned 1:1 with the OHLCV rows the site receives."""

from __future__ import annotations

import pandas as pd


def compute(df: pd.DataFrame) -> dict[str, list[float | None]]:
    close, volume = df["Close"], df["Volume"]
    return {
        "ma5": _series(close.rolling(5).mean()),
        "ma20": _series(close.rolling(20).mean()),
        "ma60": _series(close.rolling(60).mean()),
        "rsi14": _series(rsi(close, 14), digits=1),
        "volMa20": _series(volume.rolling(20).mean(), digits=0),
    }


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, pd.NA)
    return (100 - 100 / (1 + rs)).fillna(50)


def _series(s: pd.Series, digits: int = 2) -> list[float | None]:
    return [None if pd.isna(v) else round(float(v), digits) for v in s]
