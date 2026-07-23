"""Ticker metadata: market cap, sector, English names.

StockListing calls are slow (NASDAQ ≈ 9s) and rarely change, so results are
cached on disk for a day.
"""

from __future__ import annotations

from ..config import all_universe
from ..util import io, log

_CACHE_TTL = 60 * 60 * 24


def _listing(name: str):
    import FinanceDataReader as fdr
    return fdr.StockListing(name)


def _kr_meta() -> dict[str, dict]:
    cached = io.cache_get("meta_kr", _CACHE_TTL)
    if cached:
        return cached

    meta: dict[str, dict] = {}
    for board in ("KOSPI", "KOSDAQ"):
        try:
            df = _listing(board)
        except Exception as exc:
            log.warn(f"{board} listing failed: {exc}")
            continue
        for _, row in df.iterrows():
            code = str(row.get("Code", "")).zfill(6)
            if not code or code == "000000":
                continue
            meta[code] = {
                "marcap": _int(row.get("Marcap")),
                "amount": _int(row.get("Amount")),
                "shares": _int(row.get("Stocks")),
                "exchange": board,
            }

    try:
        desc = _listing("KRX-DESC")
        for _, row in desc.iterrows():
            code = str(row.get("Code", "")).zfill(6)
            if code in meta:
                meta[code]["sector"] = _str(row.get("Sector"))
                meta[code]["industry"] = _str(row.get("Industry"))
    except Exception as exc:
        log.warn(f"KRX-DESC failed: {exc}")

    io.cache_set("meta_kr", meta)
    log.ok(f"KR metadata: {len(meta)} tickers")
    return meta


def _us_meta() -> dict[str, dict]:
    cached = io.cache_get("meta_us", _CACHE_TTL)
    if cached:
        return cached

    meta: dict[str, dict] = {}
    for board in ("S&P500", "NASDAQ"):
        try:
            df = _listing(board)
        except Exception as exc:
            log.warn(f"{board} listing failed: {exc}")
            continue
        for _, row in df.iterrows():
            sym = _str(row.get("Symbol"))
            if not sym:
                continue
            entry = meta.setdefault(sym, {})
            entry.setdefault("nameEn", _str(row.get("Name")))
            sector = _str(row.get("Sector")) or _str(row.get("Industry"))
            if sector and not entry.get("sector"):
                entry["sector"] = sector

    io.cache_set("meta_us", meta)
    log.ok(f"US metadata: {len(meta)} tickers")
    return meta


def enrich() -> list[dict]:
    """Universe from config, merged with live listing metadata."""
    kr, us = _kr_meta(), _us_meta()
    out: list[dict] = []

    for item in all_universe():
        extra = (kr if item["market"] == "KR" else us).get(item["code"], {})
        merged = dict(item)
        merged["sector"] = extra.get("sector") or ("기타" if item["market"] == "KR" else "Other")
        merged["marcap"] = extra.get("marcap")
        merged["nameEn"] = extra.get("nameEn") or (item["name"] if item["market"] == "US" else None)
        if extra.get("exchange"):
            merged["exchange"] = extra["exchange"]
        out.append(merged)

    return out


def _int(value) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _str(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text and text.lower() != "nan" else None
