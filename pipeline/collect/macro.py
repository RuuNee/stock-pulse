"""Macro dashboard data — indices, FX, rates, commodities (schema §2)."""

from __future__ import annotations

from ..config import MACRO_SYMBOLS
from ..util import log
from . import prices


def collect() -> list[dict]:
    out: list[dict] = []
    for sym in MACRO_SYMBOLS:
        df = prices.fetch_ohlcv(sym["key"], years=1)
        if df is None or df.empty:
            log.warn(f"macro skip: {sym['key']}")
            continue
        quote = prices.quote_from(df)
        out.append({
            "key": sym["key"],
            "name": sym["name"],
            "market": sym["market"],
            "group": sym["group"],
            "unit": sym["unit"],
            "value": quote.get("close"),
            "change": quote.get("change"),
            "changePct": quote.get("changePct"),
            "spark": prices.spark(df, 30),
            "beginnerNote": sym["note"],
        })
    log.ok(f"macro: {len(out)}/{len(MACRO_SYMBOLS)} symbols")
    return out
