"""Cause summaries for chart events — feature R5.

For recent surges/plunges with matched news, Gemini writes a 2-3 sentence
beginner explanation of *why* the stock moved. Everything else (older events,
newsless events, or when there's no API key / quota is spent) gets a
deterministic rule summary, so the pipeline always produces something.

The LLM budget is global per run (see analyze/llm.py) — free-tier friendly.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ..config import LLM_MAX_EVENTS_PER_RUN, LLM_RECENT_DAYS
from ..util import log
from ..util import text as T
from . import llm
from .events import label_for


def _is_recent(event: dict) -> bool:
    try:
        d = datetime.strptime(event["date"], "%Y-%m-%d").date()
    except (ValueError, KeyError):
        return False
    return d >= date.today() - timedelta(days=LLM_RECENT_DAYS)


def summarize_events(ticker: dict, events: list[dict]) -> list[dict]:
    """Rule summaries for every event. AI upgrades the globally most important
    ones later via :func:`enhance_globally` (free-tier quota is scarce, so it is
    spent on the top events across the whole universe, not per ticker)."""
    for event in events:
        _rule_explain(ticker, event)
    return events


def enhance_globally(details: list[dict]) -> None:
    """Second pass: pick the most significant recent events across ALL tickers
    and have Gemini write the cause + confidence for them. Mutates in place,
    upgrading those events from rule → llm."""
    if not llm.available():
        return

    # Collect candidates (recent + has news) with their owning ticker.
    cands: list[tuple[dict, dict]] = []
    index: dict[str, dict] = {}
    for d in details:
        for e in d["events"]:
            if e.get("news") and _is_recent(e):
                cands.append((d, e))
                index[e["id"]] = e

    # Global ranking: severity, then size of move, then breadth of coverage.
    cands.sort(
        key=lambda de: (de[1]["severity"], abs(de[1]["changePct"]), len(de[1]["news"]), de[1]["date"]),
        reverse=True,
    )
    top = cands[:LLM_MAX_EVENTS_PER_RUN]
    if not top:
        return

    items = [
        {
            "id": e["id"], "name": d["name"], "code": d["code"], "market": d["market"],
            "date": e["date"], "changePct": e["changePct"], "volumeRatio": e.get("volumeRatio"),
            "news": [n["title"] for n in e["news"][:5]],
        }
        for d, e in top
    ]
    results = llm.explain_events(items)

    done = 0
    for eid, got in results.items():
        e = index.get(eid)
        if not (e and got and str(got.get("explain", "")).strip()):
            continue
        e.update({
            "headline": T.truncate(str(got.get("headline", "")), 30) or e.get("headline"),
            "explain": str(got.get("explain", "")).strip(),
            "sentiment": got.get("sentiment", e.get("sentiment", "neutral")),
            "confidence": got.get("confidence", "medium"),
            "tags": [str(t) for t in (got.get("tags") or [])][:5],
            "source": "llm",
        })
        done += 1
    log.ok(f"AI-analyzed {done}/{len(top)} top events ({llm.stats()})")


def _rule_explain(ticker: dict, event: dict) -> None:
    """Deterministic fallback: lead with the top headline, else a generic note."""
    news = event.get("news", [])
    direction = "올랐습니다" if event["changePct"] > 0 else "내렸습니다"

    if news:
        top = news[0]["title"]
        event["headline"] = T.truncate(top, 30)
        event["explain"] = (
            f"이 날 {ticker['name']}은(는) {abs(event['changePct']):.1f}% {direction}. "
            f"비슷한 시점에 \"{T.truncate(top, 40)}\" 등의 뉴스가 있었습니다. "
            "아래 관련 기사에서 자세한 배경을 확인할 수 있습니다."
        )
        # Confidence from evidence strength: several closely-matched articles
        # is a stronger basis than one weak hit. Rule-based caps at "medium".
        top_score = news[0].get("score", 0) or 0
        if len(news) >= 3 and top_score >= 1.6:
            event["confidence"] = "medium"
        elif len(news) >= 2 and top_score >= 1.4:
            event["confidence"] = "medium"
        else:
            event["confidence"] = "low"
        event["sentiment"] = T.sentiment_of(" ".join(n["title"] for n in news))
    else:
        event["headline"] = label_for(event)
        event["explain"] = (
            f"이 날 {ticker['name']}은(는) {abs(event['changePct']):.1f}% {direction}. "
            "뚜렷한 개별 뉴스는 찾지 못했습니다. 시장 전체 흐름이나 수급 영향일 수 있습니다."
        )
        event["confidence"] = "low"
        event["sentiment"] = "positive" if event["changePct"] > 0 else "negative"

    event["source"] = "rule"
    event.setdefault("tags", [])
