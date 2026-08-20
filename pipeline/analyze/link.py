"""Link news to tickers, and news to chart events.

The event window matters: a Korean stock's Wednesday move is driven by
everything published from Tuesday's close through Wednesday's close, not by
Wednesday's calendar day alone.
"""

from __future__ import annotations

from datetime import datetime, time as dtime, timedelta

from ..config import ET, KST
from ..util import text as T
from ..util.dates import parse_iso

# Local close of each market — the boundary of an event's news window.
_CLOSE = {"KR": (KST, dtime(15, 30)), "US": (ET, dtime(16, 0))}


def tag_tickers(items: list[dict], universe: list[dict]) -> list[dict]:
    """Attach matching universe tickers to each news item."""
    index = [
        {
            "code": t["code"],
            "name": t["name"],
            "market": t["market"],
            "needles": _needles(t),
        }
        for t in universe
    ]

    for item in items:
        haystack = f"{item.get('title', '')} {item.get('summary', '')}"
        existing = {t["code"] for t in item.get("tickers", [])}
        matches = list(item.get("tickers", []))

        for entry in index:
            if entry["code"] in existing:
                continue
            score = _match_score(haystack, entry, item.get("title", ""))
            if score > 0:
                matches.append({
                    "code": entry["code"], "name": entry["name"],
                    "market": entry["market"], "score": score,
                })

        matches.sort(key=lambda t: t["score"], reverse=True)
        item["tickers"] = matches[:6]

    return items


def _needles(ticker: dict) -> list[tuple[str, float, bool]]:
    """Search terms with confidence weights and case-sensitivity.

    The third field is ``case_sensitive``. Only US ticker symbols set it: they
    collide with ordinary lowercase words, and headlines always capitalise them.
    """
    out: list[tuple[str, float, bool]] = [(ticker["name"], 0.85, False)]
    for alias in ticker.get("aliases", []):
        out.append((alias, 0.75, False))
    if ticker["market"] == "US":
        out.append((ticker["code"], 0.9, True))
        if ticker.get("nameEn"):
            out.append((ticker["nameEn"], 0.85, False))
    else:
        out.append((ticker["code"], 0.95, False))  # 6-digit codes are unambiguous
    return out


def _match_score(haystack: str, entry: dict, title: str) -> float:
    best = 0.0
    for needle, weight, cased in entry["needles"]:
        if len(needle) < 2:
            continue
        if T.contains_token(haystack, needle, case_sensitive=cased):
            score = weight
            if T.contains_token(title, needle, case_sensitive=cased):
                score = min(1.0, score + 0.1)  # headline mention is stronger
            best = max(best, score)
    return round(best, 2)


def event_window(market: str, event_date: str,
                 days_before: int = 1, days_after: int = 0) -> tuple[datetime, datetime]:
    """UTC [start, end) covering the news that could explain that session.

    Default is [close-1day, close): same-session drivers. Historical backfill
    passes a wider window (days_after≥1) so next-day explanatory articles —
    "why did X drop yesterday" — still count.
    """
    tz, close = _CLOSE[market]
    day = datetime.strptime(event_date, "%Y-%m-%d").date()
    end = datetime.combine(day, close, tzinfo=tz) + timedelta(days=days_after)
    start = datetime.combine(day, close, tzinfo=tz) - timedelta(days=days_before)
    return start, end


def attach_news(events: list[dict], news: list[dict], market: str,
                *, max_items: int = 5, days_before: int = 1, days_after: int = 0) -> list[dict]:
    """Fill each event's ``news`` list with the best-matching articles."""
    dated = [(parse_iso(n.get("publishedAt")), n) for n in news]
    dated = [(ts, n) for ts, n in dated if ts]

    for event in events:
        start, end = event_window(market, event["date"], days_before, days_after)
        direction = 1 if event["changePct"] > 0 else -1
        scored: list[tuple[float, dict]] = []

        for ts, item in dated:
            if not (start <= ts < end):
                continue
            scored.append((_relevance(item, ts, end, direction), item))

        scored.sort(key=lambda x: x[0], reverse=True)
        event["news"] = [
            {
                "title": n["title"],
                "url": n["url"],
                "source": n.get("source"),
                "publishedAt": n.get("publishedAt"),
                "score": round(score, 2),
            }
            for score, n in scored[:max_items]
        ]

    return events


def _relevance(item: dict, ts: datetime, end: datetime, direction: int) -> float:
    score = float(item.get("sourceWeight", 0.7))

    # Ticker-specific feeds carry a pre-set match; general feeds are matched.
    top_ticker = max((t.get("score", 0) for t in item.get("tickers", [])), default=0)
    score += top_ticker

    # Closer to the session close = more likely to be the driver.
    hours_before = (end - ts).total_seconds() / 3600
    score += min(1.0, max(0.0, (24 - hours_before) / 24)) * 0.4

    # A negative headline on an up day is probably not the explanation.
    sentiment = T.sentiment_of(f"{item.get('title', '')} {item.get('summary', '')}")
    if (sentiment == "positive" and direction > 0) or (sentiment == "negative" and direction < 0):
        score += 0.35
    elif sentiment != "neutral":
        score -= 0.2

    score += min(item.get("dupCount", 1) - 1, 3) * 0.1  # widely reported = important
    return score
