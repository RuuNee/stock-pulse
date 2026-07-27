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
from ..analyze import indicators, link, llm, mood, score, summarize
from ..config import (
    DATA_DIR,
    EVENT_BACKFILL_MAX_AGE_DAYS,
    EVENT_BACKFILL_MAX_PER_TICKER,
    EVENT_NEWS_BACKFILL,
    RECENT_NEWS_PER_TICKER,
    NEWS_MAX_ITEMS,
    TRANSLATE_FEED_TOP,
    TRANSLATE_FOREIGN,
    TRANSLATE_MAX_ITEMS,
    TRANSLATE_TICKER_NEWS,
    all_universe,
)
from ..util import io, log
from ..util.dates import iso, next_session_date, now_kst, now_utc


def build(markets: tuple[str, ...] = ("KR", "US")) -> dict:
    started = now_utc()
    log.step(f"Building site data for {markets}")
    llm.reset()
    _TRANS.clear()

    log.step("1/6 · universe metadata")
    tickers_meta = [t for t in universe.enrich() if t["market"] in markets]

    log.step("2/6 · market news + feed translation")
    market_news = news_mod.fetch_market_feeds(markets)
    market_news = link.tag_tickers(market_news, tickers_meta)
    market_news = score.enrich(market_news)
    log.ok(f"news: {len(market_news)} items after scoring")
    # Translate the feed FIRST — it's the main foreign-news surface, so it must
    # get LLM quota before per-ticker event summaries can spend it.
    _translate_feed(market_news)

    log.step("3/6 · per-ticker data + events")
    details: list[dict] = []
    for i, meta in enumerate(tickers_meta, 1):
        log.info(f"[{i}/{len(tickers_meta)}] {meta['market']} {meta['code']} {meta['name']}")
        detail = _build_ticker(meta, market_news)
        if detail is not None:
            details.append(detail)

    log.step("4/6 · AI event analysis (top events, global)")
    summarize.enhance_globally(details)
    _translate_ticker_news(details)   # no-op unless TRANSLATE_FOREIGN is on

    log.step("5/6 · writing tickers")
    index_items: list[dict] = []
    for detail in details:
        _write_ticker(detail)
        index_items.append(_index_entry(detail))

    log.step("6/6 · macro + overview + shared files")
    macro_indices = macro_mod.collect()

    # 부분 빌드(`--market KR` 등)는 요청한 시장만 새로 만든다. 공유 파일은 통째로
    # 덮어쓰면 다른 시장 데이터가 사라지므로, 이전 파일에서 그쪽 몫을 살려 합친다.
    # (brief-* 워크플로가 `--rebuild`로 단일 시장 빌드를 돌리기 때문에 실제로 발생했다)
    prev_index = io.read_json(DATA_DIR / "tickers" / "index.json", {}) or {}
    prev_overview = io.read_json(DATA_DIR / "market" / "overview.json", {}) or {}
    prev_news = io.read_json(DATA_DIR / "news" / "latest.json", {}) or {}
    prev_manifest = io.read_json(DATA_DIR / "manifest.json", {}) or {}

    all_items = _merge_by_market(prev_index.get("items", []), index_items, markets)
    all_news = _merge_news(prev_news.get("items", []), market_news, markets)
    overview = _build_overview(macro_indices, index_items, markets, prev_overview)

    io.write_json(DATA_DIR / "tickers" / "index.json",
                  {"generatedAt": iso(started), "items": all_items})
    io.write_json(DATA_DIR / "market" / "overview.json", overview)
    io.write_json(DATA_DIR / "news" / "latest.json",
                  {"generatedAt": iso(started), "items": all_news})

    manifest = _manifest(started, all_items, all_news, markets, prev_manifest)
    io.write_json(DATA_DIR / "manifest.json", manifest)

    log.ok(f"done · {len(index_items)}/{len(all_items)} tickers, "
           f"{len(market_news)}/{len(all_news)} news · {llm.stats()}")
    return {
        "tickers": all_items,
        "overview": overview,
        "news": all_news,
        "manifest": manifest,
    }


def _merge_by_market(previous: list[dict], fresh: list[dict],
                     markets: tuple[str, ...]) -> list[dict]:
    """이번에 빌드하지 않은 시장의 항목을 이전 파일에서 살려 합친다."""
    kept = [it for it in previous if it.get("market") not in markets]
    return fresh + kept


def _merge_news(previous: list[dict], fresh: list[dict],
                markets: tuple[str, ...]) -> list[dict]:
    """뉴스도 같은 원리. url 중복은 이번 빌드 결과를 우선한다.

    `GLOBAL` 뉴스는 어느 시장 빌드에서도 나올 수 있어 `markets`에 안 걸리는데,
    url 중복 제거가 그 몫을 처리한다.
    """
    seen = {n.get("url") for n in fresh if n.get("url")}
    kept = [n for n in previous
            if n.get("market") not in markets and n.get("url") not in seen]
    out = fresh + kept
    out.sort(key=lambda n: n.get("importance", 0), reverse=True)
    return out[:NEWS_MAX_ITEMS]


def build_pulse(markets: tuple[str, ...] = ("KR", "US")) -> dict:
    """Lightweight intraday refresh — the "always-current economic snapshot".

    Rebuilds only the cheap, fast-moving parts: macro indices (지수·환율·VIX·
    유가·금), market mood, and the news feed. Skips the heavy per-ticker rebuild
    (charts/events/AI), so it can run every couple of hours within the free
    Actions budget. Sectors/movers are carried over from the last full sync.
    """
    started = now_utc()
    log.step(f"Pulse (light) update for {markets}")

    macro_indices = macro_mod.collect()
    # Use the config universe (instant) rather than enrich() (slow listing
    # fetch) — news tagging only needs code/name/aliases/market.
    tickers_meta = [t for t in all_universe() if t["market"] in markets]
    market_news = news_mod.fetch_market_feeds(markets)
    market_news = link.tag_tickers(market_news, tickers_meta)
    market_news = score.enrich(market_news)

    prev = io.read_json(DATA_DIR / "market" / "overview.json", {}) or {}
    movers = prev.get("movers", {})
    sectors = prev.get("sectors", {})
    # build()와 같은 이유로 요청한 시장만 갱신하고 나머지는 이전 값을 유지한다.
    market_mood = dict(prev.get("marketMood") or {})
    for m in markets:
        market_mood[m] = mood.score_market(
            m, macro_indices, movers.get(m, {"up": [], "down": []}))

    prev_news = io.read_json(DATA_DIR / "news" / "latest.json", {}) or {}
    all_news = _merge_news(prev_news.get("items", []), market_news, markets)

    overview = {
        "generatedAt": iso(started),
        "indices": macro_indices,
        "sectors": sectors,
        "movers": movers,
        "marketMood": market_mood,
    }
    io.write_json(DATA_DIR / "market" / "overview.json", overview)
    io.write_json(DATA_DIR / "news" / "latest.json",
                  {"generatedAt": iso(started), "items": all_news})

    manifest = io.read_json(DATA_DIR / "manifest.json", {}) or {}
    manifest["generatedAt"] = iso(started)
    manifest["generatedAtKst"] = now_kst().strftime("%Y-%m-%d %H:%M")
    io.write_json(DATA_DIR / "manifest.json", manifest)

    log.ok(f"pulse done · {len(macro_indices)} indices, "
           f"{len(market_news)}/{len(all_news)} news")
    return {"overview": overview, "news": all_news}


# Run-scoped translation cache: source string (en) → Korean.
_TRANS: dict[str, str] = {}


def _apply_trans(n: dict) -> None:
    t = _TRANS.get(n.get("title"))
    if t:
        n["titleKo"] = t
    s = _TRANS.get(n.get("summary"))
    if s:
        n["summaryKo"] = s


def _translate(strings: list[str]) -> None:
    """Translate uncached strings (up to the per-run cap) into _TRANS."""
    room = TRANSLATE_MAX_ITEMS - len(_TRANS)
    todo, seen = [], set()
    for s in strings:
        if s and s not in _TRANS and s not in seen:
            seen.add(s)
            todo.append(s)
    todo = todo[:max(0, room)]
    if not todo:
        return
    for en, ko in zip(todo, llm.translate(todo)):
        if ko and ko != en:
            _TRANS[en] = ko


def _translate_feed(market_news: list[dict]) -> None:
    """Priority pass: translate the top-importance US/GLOBAL feed items. Bounded
    to TRANSLATE_FEED_TOP so it fits the free-tier daily budget."""
    if not (TRANSLATE_FOREIGN and llm.available()):
        return
    feed = [n for n in market_news if n.get("market") in ("US", "GLOBAL")]
    feed.sort(key=lambda n: n.get("importance", 0), reverse=True)
    top = feed[:TRANSLATE_FEED_TOP]
    texts: list[str] = []
    for n in top:
        texts.append(n.get("title"))
        texts.append(n.get("summary"))
    _translate([t for t in texts if t])
    for n in feed:  # apply to the whole feed (cache hits only where translated)
        _apply_trans(n)
    log.ok(f"translated feed top-{len(top)}: {len(_TRANS)} strings cached")


def _translate_ticker_news(details: list[dict]) -> None:
    """US tickers' recent + event news. Reuses the feed cache for free; only
    spends new calls when TRANSLATE_TICKER_NEWS is on."""
    def foreign(d: dict):
        if d["market"] != "US":
            return []
        out = list(d.get("recentNews", []))
        for e in d.get("events", []):
            out.extend(e.get("news", []))
        return out

    if TRANSLATE_TICKER_NEWS and TRANSLATE_FOREIGN and llm.available():
        titles = [n.get("title") for d in details for n in foreign(d)]
        _translate([t for t in titles if t])
    for d in details:
        for n in foreign(d):
            _apply_trans(n)


def _build_ticker(meta: dict, market_news: list[dict]) -> dict | None:
    df = prices.fetch_ohlcv(meta["code"])
    if df is None or df.empty:
        return None

    quote = prices.quote_from(df)
    quote["marcap"] = meta.get("marcap")

    events = events_mod.detect(df, meta["code"])

    # ETFs are baskets: single-company news doesn't explain their moves, so skip
    # the expensive per-ticker Google News fetch + historical backfill. They keep
    # price/chart/search; any market news tagged to them still shows.
    is_etf = meta.get("isEtf", False)
    tagged_market = [n for n in market_news
                     if any(t["code"] == meta["code"] for t in n.get("tickers", []))]
    ticker_news = [] if is_etf else news_mod.fetch_ticker_news(meta)
    combined = news_mod.dedupe(ticker_news + tagged_market)
    combined = score.enrich(combined)

    events = link.attach_news(events, combined, meta["market"])
    if not is_etf:
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
        # Wider window: historical drivers are often reported the next day too.
        linked = link.attach_news([dict(event)], hist, meta["market"],
                                  max_items=5, days_before=2, days_after=2)
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


def _build_overview(macro_indices, index_items, markets, previous=None) -> dict:
    """이번에 빌드한 시장만 갱신하고 나머지는 이전 overview에서 가져온다.

    `indices`(매크로)는 시장과 무관하게 매번 전체를 수집하므로 그대로 교체한다.
    """
    previous = previous or {}
    sectors = dict(previous.get("sectors") or {})
    movers = dict(previous.get("movers") or {})
    market_mood = dict(previous.get("marketMood") or {})
    for m in markets:
        sectors[m] = _sector_heatmap(index_items, m)
        movers[m] = _movers(index_items, m)
        market_mood[m] = mood.score_market(m, macro_indices, movers[m])
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


def _manifest(started, index_items, market_news, markets, previous=None) -> dict:
    events_total = sum(it.get("eventCount", 0) for it in index_items)
    # 빌드하지 않은 시장의 블록은 이전 manifest 값을 유지한다.
    market_blocks = dict((previous or {}).get("markets") or {})
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
