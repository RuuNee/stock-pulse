"""Orchestrate collection + analysis into the static JSON the web app reads.

Pipeline per run:
  universe metadata → per-ticker (prices, indicators, events, news) →
  ticker files + index + market overview + news feed + manifest.

Everything is written under data/ (schema in md파일/02-데이터스키마.md).
"""

from __future__ import annotations

from ..collect import macro as macro_mod
from ..collect import news as news_mod
from ..collect import prices, universe
from ..analyze import events as events_mod
from ..analyze import indicators, link, mood, score, summarize
from ..config import (
    DATA_DIR,
    EVENT_BACKFILL_MAX_AGE_DAYS,
    EVENT_BACKFILL_MAX_PER_TICKER,
    EVENT_NEWS_BACKFILL,
    RECENT_NEWS_PER_TICKER,
    NEWS_MAX_ITEMS,
    all_universe,
)
from ..util import io, log
from ..util.dates import iso, next_session_date, now_kst, now_utc


def build(markets: tuple[str, ...] = ("KR", "US")) -> dict:
    started = now_utc()
    log.step(f"Building site data for {markets}")

    log.step("1/5 · universe metadata")
    tickers_meta = [t for t in universe.enrich() if t["market"] in markets]

    log.step("2/5 · market news")
    market_news = news_mod.fetch_market_feeds(markets)
    market_news = link.tag_tickers(market_news, tickers_meta)
    market_news = score.enrich(market_news)
    log.ok(f"news: {len(market_news)} items after scoring")

    log.step("3/5 · per-ticker data + events")
    index_items: list[dict] = []
    for i, meta in enumerate(tickers_meta, 1):
        log.info(f"[{i}/{len(tickers_meta)}] {meta['market']} {meta['code']} {meta['name']}")
        detail = _build_ticker(meta, market_news)
        if detail is None:
            continue
        _write_ticker(detail)
        index_items.append(_index_entry(detail))

    log.step("4/5 · macro + market overview")
    macro_indices = macro_mod.collect()
    overview = _build_overview(macro_indices, index_items, market_news, markets)

    log.step("5/5 · writing shared files")
    io.write_json(DATA_DIR / "tickers" / "index.json",
                  {"generatedAt": iso(started), "items": index_items})
    io.write_json(DATA_DIR / "market" / "overview.json", overview)
    io.write_json(DATA_DIR / "news" / "latest.json",
                  {"generatedAt": iso(started), "items": market_news[:NEWS_MAX_ITEMS]})

    manifest = _manifest(started, index_items, market_news, markets)
    io.write_json(DATA_DIR / "manifest.json", manifest)

    log.ok(f"done · {len(index_items)} tickers, {len(market_news)} news")
    return {
        "tickers": index_items,
        "overview": overview,
        "news": market_news,
        "manifest": manifest,
    }


def _build_ticker(meta: dict, market_news: list[dict]) -> dict | None:
    df = prices.fetch_ohlcv(meta["code"])
    if df is None or df.empty:
        return None

    quote = prices.quote_from(df)
    quote["marcap"] = meta.get("marcap")

    events = events_mod.detect(df, meta["code"])

    # Per-ticker news = ticker-specific feed + market news already tagged to it.
    ticker_news = news_mod.fetch_ticker_news(meta)
    tagged_market = [n for n in market_news
                     if any(t["code"] == meta["code"] for t in n.get("tickers", []))]
    combined = news_mod.dedupe(ticker_news + tagged_market)
    combined = score.enrich(combined)

    events = link.attach_news(events, combined, meta["market"])
    _backfill_event_news(meta, events)
    events = summarize.summarize_events(meta, events)

    return {
        "code": meta["code"],
        "name": meta["name"],
        "nameEn": meta.get("nameEn"),
        "market": meta["market"],
        "exchange": meta.get("exchange"),
        "sector": meta.get("sector"),
        "currency": meta["currency"],
        "updatedAt": iso(now_utc()),
        "quote": quote,
        "ohlcv": {
            "columns": ["d", "o", "h", "l", "c", "v"],
            "rows": prices.to_rows(df),
        },
        "indicators": indicators.compute(df),
        "events": events,
        "recentNews": [_news_brief(n) for n in combined[:RECENT_NEWS_PER_TICKER]],
        "_spark": prices.spark(df, 30),
    }


def _backfill_event_news(meta: dict, events: list[dict]) -> None:
    """For the top newsless events, fetch date-scoped historical news (R5).

    Bounded per ticker so a full sync stays under budget. Mutates events in
    place, attaching up to 5 matched articles each.
    """
    if not EVENT_NEWS_BACKFILL:
        return
    from datetime import date, timedelta

    cutoff = (date.today() - timedelta(days=EVENT_BACKFILL_MAX_AGE_DAYS)).isoformat()
    candidates = [
        e for e in events
        if not e.get("news") and e["date"] >= cutoff
    ]
    candidates.sort(key=lambda e: (e["severity"], abs(e["changePct"])), reverse=True)

    done = 0
    for event in candidates[:EVENT_BACKFILL_MAX_PER_TICKER]:
        hist = news_mod.fetch_event_news(meta, event["date"])
        if not hist:
            continue
        hist = score.enrich(hist)
        linked = link.attach_news([dict(event)], hist, meta["market"], max_items=5)
        if linked and linked[0].get("news"):
            event["news"] = linked[0]["news"]
            done += 1
    if done:
        log.info(f"    {meta['code']}: backfilled news for {done} events")


def _write_ticker(detail: dict) -> None:
    payload = {k: v for k, v in detail.items() if not k.startswith("_")}
    io.write_json(
        DATA_DIR / "tickers" / detail["market"] / f"{detail['code']}.json",
        payload, quiet=True,
    )


def _index_entry(detail: dict) -> dict:
    q = detail["quote"]
    latest_event = detail["events"][0]["date"] if detail["events"] else None
    return {
        "code": detail["code"],
        "name": detail["name"],
        "nameEn": detail.get("nameEn"),
        "market": detail["market"],
        "exchange": detail.get("exchange"),
        "sector": detail.get("sector"),
        "currency": detail["currency"],
        "close": q.get("close"),
        "changePct": q.get("changePct"),
        "marcap": q.get("marcap"),
        "spark": detail["_spark"],
        "eventCount": len(detail["events"]),
        "latestEvent": latest_event,
        "date": q.get("date"),
    }


def _build_overview(macro_indices, index_items, market_news, markets) -> dict:
    sectors = {m: _sector_heatmap(index_items, m) for m in markets}
    movers = {m: _movers(index_items, m) for m in markets}
    market_mood = {
        m: mood.score_market(m, macro_indices, movers[m]) for m in markets
    }
    return {
        "generatedAt": iso(now_utc()),
        "indices": macro_indices,
        "sectors": sectors,
        "movers": movers,
        "marketMood": market_mood,
    }


def _sector_heatmap(items: list[dict], market: str) -> list[dict]:
    buckets: dict[str, list[dict]] = {}
    for it in items:
        if it["market"] != market or it.get("changePct") is None:
            continue
        buckets.setdefault(it.get("sector") or "기타", []).append(it)

    out = []
    for name, members in buckets.items():
        top = max(members, key=lambda x: x.get("changePct") or -999)
        out.append({
            "name": name,
            "changePct": round(sum(m["changePct"] for m in members) / len(members), 2),
            "count": len(members),
            "topName": top["name"],
            "topPct": top.get("changePct"),
        })
    out.sort(key=lambda s: s["changePct"], reverse=True)
    return out


def _movers(items: list[dict], market: str) -> dict:
    ranked = [it for it in items if it["market"] == market and it.get("changePct") is not None]
    ranked.sort(key=lambda x: x["changePct"], reverse=True)
    return {
        "up": [_mover_ref(x) for x in ranked[:8]],
        "down": [_mover_ref(x) for x in reversed(ranked[-8:])] if len(ranked) > 1 else [],
    }


def _mover_ref(it: dict) -> dict:
    return {
        "code": it["code"],
        "name": it["name"],
        "market": it["market"],
        "changePct": it.get("changePct"),
        "close": it.get("close"),
        "reason": None,  # filled from latest event in brief; keep overview light
    }


def _news_brief(n: dict) -> dict:
    return {
        "id": n["id"],
        "title": n["title"],
        "summary": n.get("summary"),
        "url": n["url"],
        "source": n.get("source"),
        "market": n.get("market"),
        "publishedAt": n.get("publishedAt"),
        "category": n.get("category"),
        "tags": n.get("tags", []),
        "tickers": n.get("tickers", []),
        "importance": n.get("importance"),
        "sentiment": n.get("sentiment"),
    }


def _manifest(started, index_items, market_news, markets) -> dict:
    events_total = sum(it["eventCount"] for it in index_items)
    market_blocks = {}
    for m in markets:
        last = _last_trading_day(index_items, m)
        market_blocks[m] = {
            "lastTradingDay": last,
            "briefDate": next_session_date(m).isoformat(),
        }
    return {
        "version": 1,
        "generatedAt": iso(started),
        "generatedAtKst": now_kst().strftime("%Y-%m-%d %H:%M"),
        "counts": {
            "tickers": len(index_items),
            "news": len(market_news),
            "events": events_total,
        },
        "markets": market_blocks,
    }


def _last_trading_day(index_items, market: str) -> str | None:
    days = [it["date"] for it in index_items
            if it["market"] == market and it.get("date")]
    return max(days) if days else None
