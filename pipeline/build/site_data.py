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
from ..analyze import indicators, link, llm, mood, score, summarize, technical
from ..config import (
    DATA_DIR,
    EVENT_BACKFILL_MAX_AGE_DAYS,
    EVENT_BACKFILL_MAX_PER_TICKER,
    EVENT_NEWS_BACKFILL,
    RECENT_NEWS_PER_TICKER,
    NEWS_MAX_ITEMS,
    HISTORY_YEARS,
    TIER2_EVENT_MAX,
    TIER2_HISTORY_YEARS,
    TIER2_RECENT_NEWS,
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
    # `briefDate`는 웹이 "오늘 브리핑이 아직 안 나왔다"를 판단하는 기준값이다.
    # full sync(하루 2회)에서만 갱신하면 반나절씩 옛 날짜가 남아 웹이 낡은 브리핑을
    # 최신인 것처럼 보여준다. 2시간마다 도는 pulse에서 같이 밀어 준다.
    # `lastTradingDay`는 종목 데이터가 있어야 구하므로 full sync 몫으로 남긴다.
    blocks = dict(manifest.get("markets") or {})
    for m in markets:
        block = dict(blocks.get(m) or {})
        block["briefDate"] = next_session_date(m).isoformat()
        blocks[m] = block
    manifest["markets"] = blocks
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


def _no_backslide(meta: dict, df):
    """새로 받은 마지막 봉이 이미 가진 것보다 과거면 저장된 봉으로 되돌린다.

    시세 소스가 직전 세션 봉을 일시적으로 빼고 줄 때가 있다. 2026-08-04 에
    실제로 겪었다 (AAPL):

        08-03 22:58 UTC (18:58 ET)  quote 2026-08-03  303.42   ← 정상
        08-04 10:30 UTC (06:30 ET)  quote 2026-07-31  308.91   ← 08-03 을 잃음

    이른 아침 ET 구간에서 소스가 전날 일봉을 잠깐 내렸고, 우리가 그걸 그대로
    덮어써서 미장 하루치가 통째로 사라졌다. 화면에는 "미장이 7/31에 멈췄다"로
    보였고, 그 상태가 다음 정기 실행까지 12시간 갔다.

    **데이터는 뒤로 가지 않는다** — 소스를 못 믿을 때의 마지막 방어선이다.
    종목을 건너뛰지는 않는다. `_build_ticker` 가 None 을 내면 그 종목이
    `index.json` 에서 통째로 빠져 검색·목록에서 사라지기 때문이다. 낡은 값은
    불편하지만 사라진 종목은 고장이다.
    """
    path = DATA_DIR / "tickers" / meta["market"] / f"{meta['code']}.json"
    prev = io.read_json(path)
    prev_date = ((prev or {}).get("quote") or {}).get("date")
    if not prev_date:
        return df

    new_date = df.index[-1].strftime("%Y-%m-%d")
    if new_date >= prev_date:
        return df

    restored = prices.from_rows(((prev.get("ohlcv") or {}).get("rows")) or [])
    if restored is None or restored.empty:
        return df
    log.warn(f"{meta['market']} {meta['code']}: 소스가 뒤로 감 "
             f"({prev_date} → {new_date}) — 저장된 봉 유지")
    return restored


def _build_ticker(meta: dict, market_news: list[dict]) -> dict | None:
    # 확대분(tier 2)은 히스토리를 짧게 받는다. 종목 파일 하나가 90KB 인데
    # 수백 개가 매시간 커밋되면 .git 이 하루 수십 MB 씩 불어난다.
    is_tier2 = meta.get("tier", 1) == 2
    years = TIER2_HISTORY_YEARS if is_tier2 else HISTORY_YEARS
    df = prices.fetch_ohlcv(meta["code"], years=years)
    # 정기 실행(07:30·21:30 UTC)은 양 시장이 다 닫힌 시각이라 안 걸리지만,
    # 수동 dispatch 는 장중에 돌 수 있다. 그때 진행 중인 봉이 종가로 들어가면
    # 차트 분석 신호까지 그 값으로 계산된다.
    df = prices.drop_unclosed(df, meta["market"])
    if df is None or df.empty:
        return None
    df = _no_backslide(meta, df)

    quote = prices.quote_from(df)
    quote["marcap"] = meta.get("marcap")

    events = events_mod.detect(df, meta["code"],
                               limit=TIER2_EVENT_MAX if is_tier2 else None)

    # ETFs are baskets: single-company news doesn't explain their moves, so skip
    # the expensive per-ticker fetch + historical backfill. They keep
    # price/chart/search; any market news tagged to them still shows.
    #
    # Tier 2 is gated the same way but on movement instead of type — see
    # `universe.wants_news`. Both still pick up market-feed news tagged to them,
    # so a quiet tier-2 name is never fully dark.
    is_etf = meta.get("isEtf", False)
    tagged_market = [n for n in market_news
                     if any(t["code"] == meta["code"] for t in n.get("tickers", []))]
    fetch_news = universe.wants_news(meta, events)
    ticker_news = news_mod.fetch_ticker_news(meta) if fetch_news else []
    combined = news_mod.dedupe(ticker_news + tagged_market)
    combined = score.enrich(combined)

    events = link.attach_news(events, combined, meta["market"])
    # 과거 이벤트 백필은 종목당 최대 6번의 date-scoped 쿼리(각 1.2초 sleep)라
    # 종목당 7초까지 든다. 코어에만 돌린다 — 확대분까지 켜면 sync 가 몇 시간이 된다.
    if not is_etf and not is_tier2:
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
        "tier": 2 if is_tier2 else 1,
        "updatedAt": iso(now_utc()),
        "quote": quote,
        "ohlcv": {
            "columns": ["d", "o", "h", "l", "c", "v"],
            "rows": prices.to_rows(df),
        },
        "indicators": indicators.compute(df),
        # 차트 분석은 순수 계산이라 LLM 예산도 네트워크도 쓰지 않는다.
        "analysis": technical.analyze(df),
        "events": events,
        "recentNews": [_news_brief(n) for n in
                       combined[:TIER2_RECENT_NEWS if is_tier2 else RECENT_NEWS_PER_TICKER]],
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
        "tier": detail.get("tier", 1),
        "close": q.get("close"),
        "changePct": q.get("changePct"),
        "marcap": q.get("marcap"),
        "spark": detail["_spark"],
        "eventCount": len(detail["events"]),
        "latestEvent": latest_event,
        # 목록·브리핑이 종목 파일을 열지 않고도 신호를 보여줄 수 있게 압축본을 싣는다.
        "analysis": technical.brief_entry(detail),
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
