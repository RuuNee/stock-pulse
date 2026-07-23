"""Detect the days a chart actually moved — the anchors for news markers.

A day becomes an event when the move is large in absolute terms *or* large
relative to the stock's own recent volatility, or when volume explodes, or the
open gaps away from the previous close. Thresholds live in config.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from ..config import (
    EVENT_ABS_PCT,
    EVENT_GAP_PCT,
    EVENT_LOOKBACK_DAYS,
    EVENT_SEVERITY_BANDS,
    EVENT_VOLUME_RATIO,
    EVENT_ZSCORE,
)


def detect(df: pd.DataFrame, code: str) -> list[dict]:
    if df is None or len(df) < 30:
        return []

    work = df.copy()
    work["ret"] = work["Close"].pct_change() * 100
    # shift(1) so the day itself never inflates its own baseline
    work["retStd"] = work["ret"].rolling(60, min_periods=20).std().shift(1)
    work["volMa20"] = work["Volume"].rolling(20, min_periods=5).mean().shift(1)
    work["prevClose"] = work["Close"].shift(1)
    work["gap"] = (work["Open"] - work["prevClose"]) / work["prevClose"] * 100

    cutoff = pd.Timestamp(date.today() - timedelta(days=EVENT_LOOKBACK_DAYS))
    work = work[work.index >= cutoff]

    events: list[dict] = []
    for ts, row in work.iterrows():
        ret = row["ret"]
        if pd.isna(ret):
            continue

        std = row["retStd"]
        z = abs(ret) / std if std and std > 0.3 else 0.0
        vol_ratio = (row["Volume"] / row["volMa20"]
                     if row["volMa20"] and row["volMa20"] > 0 else 0.0)
        gap = row["gap"] if pd.notna(row["gap"]) else 0.0

        kind = _classify(ret, z, vol_ratio, gap)
        if not kind:
            continue

        events.append({
            "id": f"{code}-{ts:%Y-%m-%d}",
            "date": ts.strftime("%Y-%m-%d"),
            "type": kind,
            "severity": _severity(ret, z, vol_ratio),
            "changePct": round(float(ret), 2),
            "zScore": round(float(z), 2) if z else None,
            "volumeRatio": round(float(vol_ratio), 2) if vol_ratio else None,
            "gapPct": round(float(gap), 2) if abs(gap) >= 0.5 else None,
            "close": round(float(row["Close"]), 4),
            "volume": int(row["Volume"]) if pd.notna(row["Volume"]) else 0,
        })

    events.sort(key=lambda e: e["date"], reverse=True)
    return events


def _classify(ret: float, z: float, vol_ratio: float, gap: float) -> str | None:
    big_move = abs(ret) >= EVENT_ABS_PCT or z >= EVENT_ZSCORE
    if big_move:
        return "surge" if ret > 0 else "plunge"
    if vol_ratio >= EVENT_VOLUME_RATIO and abs(ret) >= 1.0:
        return "volumeSpike"
    if abs(gap) >= EVENT_GAP_PCT:
        return "gapUp" if gap > 0 else "gapDown"
    return None


def _severity(ret: float, z: float, vol_ratio: float) -> int:
    level = 1
    for threshold, value in EVENT_SEVERITY_BANDS:
        if abs(ret) >= threshold:
            level = value
    if z >= 3.0 or vol_ratio >= 4.0:
        level = min(3, level + 1)
    return level


def label_for(event: dict) -> str:
    """Fallback marker label when no news explains the move."""
    pct = event["changePct"]
    return {
        "surge": f"+{pct:.1f}% 급등",
        "plunge": f"{pct:.1f}% 급락",
        "volumeSpike": "거래량 급증",
        "gapUp": "갭 상승 출발",
        "gapDown": "갭 하락 출발",
    }.get(event["type"], f"{pct:+.1f}%")
