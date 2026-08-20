"""Ticker metadata: market cap, sector, English names.

StockListing calls are slow (NASDAQ ≈ 9s) and rarely change, so results are
cached on disk for a day.
"""

from __future__ import annotations

from datetime import date, timedelta

from ..config import (
    TIER2_KR_MAX,
    TIER2_NEWS_EVENT_DAYS,
    TIER2_US_MAX,
    TIER2_US_SOURCE,
    UNIVERSE_TIER2,
    all_universe,
)
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
                "name": _str(row.get("Name")),
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
    """Universe from config, merged with live listing metadata.

    Tier 1 (config) first, then the auto-filled tier 2 expansion. Order matters:
    downstream code dedupes by code and keeps the first hit, so a hand-curated
    entry (with its Korean aliases) always beats its tier-2 twin.
    """
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

    if UNIVERSE_TIER2:
        seen = {(i["market"], i["code"]) for i in out}
        expansion = _tier2_us(us, seen) + _tier2_kr(kr, seen)
        log.ok(f"tier 2 expansion: +{len(expansion)} tickers")
        out.extend(expansion)

    return out


def _tier2_us(us_meta: dict[str, dict], seen: set) -> list[dict]:
    """S&P500 constituents that aren't already hand-curated.

    The listing is the same one `_us_meta` already caches, so this costs no
    extra network call on a warm cache.
    """
    try:
        df = _listing(TIER2_US_SOURCE)
    except Exception as exc:
        log.warn(f"{TIER2_US_SOURCE} listing failed, tier 2 US skipped: {exc}")
        return []

    out: list[dict] = []
    for _, row in df.iterrows():
        if len(out) >= TIER2_US_MAX:
            break
        code = _str(row.get("Symbol"))
        if not code or ("US", code) in seen:
            continue
        seen.add(("US", code))
        extra = us_meta.get(code, {})
        name = extra.get("nameEn") or _str(row.get("Name")) or code
        out.append(_tier2_entry(code, name, "US", "USD", name,
                                extra.get("sector") or "Other", extra.get("marcap")))
    return out


def _tier2_kr(kr_meta: dict[str, dict], seen: set) -> list[dict]:
    """Top-marcap KOSPI/KOSDAQ names that aren't already hand-curated.

    KRX listing carries marcap, so ranking needs no extra fetch. Names come from
    the listing too — tier 2 has no hand-written Korean aliases, which is why
    these get a lower news-tagging confidence than tier 1.
    """
    ranked = sorted(
        ((code, m) for code, m in kr_meta.items()
         if m.get("marcap") and not _is_preferred(code)),
        key=lambda kv: kv[1]["marcap"], reverse=True,
    )

    out: list[dict] = []
    for code, extra in ranked:
        if len(out) >= TIER2_KR_MAX:
            break
        if ("KR", code) in seen:
            continue
        name = extra.get("name")
        if not name:
            continue
        seen.add(("KR", code))
        entry = _tier2_entry(code, name, "KR", "KRW", None,
                             extra.get("sector") or "기타", extra.get("marcap"))
        entry["exchange"] = extra.get("exchange") or "KRX"
        out.append(entry)
    return out


def _is_preferred(code: str) -> bool:
    """우선주인가.

    KRX 는 보통주 코드 끝자리를 0 으로, 우선주를 5(구형)·7·9(신형) 로 매긴다.
    우선주는 본주와 재료가 같아서 뉴스도 이벤트도 겹치기만 하고, 시총 순으로
    자르면 삼성전자우처럼 상위를 먹는다 — 확대분 자리를 낭비한다.
    """
    return len(code) == 6 and code[-1] != "0"


def _tier2_entry(code, name, market, currency, name_en, sector, marcap) -> dict:
    return {
        "code": code,
        "name": name,
        "market": market,
        "exchange": "KRX" if market == "KR" else "US",
        "aliases": [],
        "currency": currency,
        "isEtf": False,
        "tier": 2,
        "nameEn": name_en,
        "sector": sector,
        "marcap": marcap,
    }


def wants_news(meta: dict, events: list[dict], today: date | None = None) -> bool:
    """Should this ticker's per-ticker news be fetched on this run?

    Tier 1 always: a quiet day is exactly when a surprise headline (product
    launch, lawsuit) matters, and skipping it would be a regression against the
    old behaviour. Tier 2 only when the chart actually moved recently — several
    hundred silent RSS calls per sync is what makes a big universe unaffordable.
    """
    if meta.get("isEtf"):
        return False
    if meta.get("tier", 1) == 1:
        return True
    if not events:
        return False
    cutoff = ((today or date.today()) - timedelta(days=TIER2_NEWS_EVENT_DAYS)).isoformat()
    return any(e.get("date", "") >= cutoff for e in events)


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
