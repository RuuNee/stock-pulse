"""RSS news collection.

Two tiers:

1. **Market feeds** — 21 verified sources (config.FEEDS) giving the general
   国장/미장 news flow.
2. **Per-ticker feeds** — Yahoo's ticker RSS for US names and Google News
   search for Korean ones. This tier is what makes the chart markers possible;
   see md파일/01-데이터소스.md §3.
"""

from __future__ import annotations

import calendar
import socket
import time
from datetime import datetime, timezone
from urllib.parse import quote

from ..config import (
    FEEDS,
    GOOGLE_NEWS_DELAY_SEC,
    GOOGLE_NEWS_RSS,
    HTTP_TIMEOUT,
    USER_AGENT,
    YAHOO_TICKER_RSS,
)
from ..util import log, text as T


def _parse(url: str):
    # feedparser has no timeout parameter and relies on the global socket
    # default — without this a single hung feed server blocks the whole run.
    import feedparser
    prev = socket.getdefaulttimeout()
    socket.setdefaulttimeout(HTTP_TIMEOUT)
    try:
        return feedparser.parse(url, agent=USER_AGENT)
    finally:
        socket.setdefaulttimeout(prev)


def _published(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def _entry_to_item(entry, *, source: str, source_key: str, market: str,
                   weight: float) -> dict | None:
    title = T.strip_source_suffix(T.clean_html(entry.get("title")))
    url = (entry.get("link") or "").strip()
    if not title or not url or len(title) < 6:
        return None

    published = _published(entry)
    summary = T.truncate(T.clean_html(entry.get("summary") or entry.get("description")), 220)

    return {
        "id": T.news_id(url),
        "title": title,
        "summary": summary,
        "url": url,
        "source": source,
        "sourceKey": source_key,
        "sourceWeight": weight,
        "market": market,
        "publishedAt": published.strftime("%Y-%m-%dT%H:%M:%SZ") if published else None,
        "_dedup": T.dedup_key(title, url),
    }


def fetch_market_feeds(markets: tuple[str, ...] = ("KR", "US")) -> list[dict]:
    """General market news. A dead feed is logged and skipped, never fatal."""
    items: list[dict] = []
    live = dead = 0

    for key, feed in FEEDS.items():
        if feed["market"] not in markets:
            continue
        try:
            parsed = _parse(feed["url"])
            entries = parsed.entries or []
        except Exception as exc:
            log.warn(f"feed error {key}: {exc}")
            dead += 1
            continue

        if not entries:
            log.warn(f"feed empty {key}")
            dead += 1
            continue

        live += 1
        for entry in entries:
            item = _entry_to_item(entry, source=feed["name"], source_key=key,
                                  market=feed["market"], weight=feed["weight"])
            if item:
                items.append(item)

    log.ok(f"market feeds: {live} live / {dead} dead → {len(items)} raw items")
    return dedupe(items)


def fetch_ticker_news(ticker: dict, *, limit: int = 25) -> list[dict]:
    """News for a single ticker, used for chart-event matching."""
    if ticker["market"] == "US":
        url = YAHOO_TICKER_RSS.format(ticker=ticker["code"])
        source_key = "yahoo_ticker"
        source = "Yahoo Finance"
    else:
        query = quote(f'"{ticker["name"]}" 주가')
        url = GOOGLE_NEWS_RSS.format(query=query)
        source_key = "google_news"
        source = "Google News"
        time.sleep(GOOGLE_NEWS_DELAY_SEC)  # Google News rate-limits aggressively

    try:
        parsed = _parse(url)
        entries = (parsed.entries or [])[:limit]
    except Exception as exc:
        log.warn(f"ticker news failed {ticker['code']}: {exc}")
        return []

    items: list[dict] = []
    for entry in entries:
        item = _entry_to_item(entry, source=source, source_key=source_key,
                              market=ticker["market"], weight=0.8)
        if not item:
            continue
        # Google News wraps the real publisher name in entry.source.
        publisher = None
        raw_source = entry.get("source")
        if isinstance(raw_source, dict):
            publisher = raw_source.get("title")
        elif raw_source:
            publisher = getattr(raw_source, "title", None)
        if publisher:
            item["source"] = T.clean_html(publisher)

        item["tickers"] = [{
            "code": ticker["code"], "name": ticker["name"],
            "market": ticker["market"], "score": 0.95,
        }]
        items.append(item)

    return dedupe(items)


def dedupe(items: list[dict]) -> list[dict]:
    """Keep the highest-weight copy of each story.

    ``_dedup`` may already have been stripped (e.g. items that passed through
    score.enrich); recompute it from title+url in that case.
    """
    best: dict[str, dict] = {}
    for item in items:
        key = item.get("_dedup") or T.dedup_key(item.get("title", ""), item.get("url", ""))
        current = best.get(key)
        if current is None:
            item["dupCount"] = 1
            best[key] = item
            continue
        current["dupCount"] = current.get("dupCount", 1) + 1
        if item["sourceWeight"] > current["sourceWeight"]:
            item["dupCount"] = current["dupCount"]
            best[key] = item

    out = list(best.values())
    out.sort(key=lambda x: x.get("publishedAt") or "", reverse=True)
    return out
