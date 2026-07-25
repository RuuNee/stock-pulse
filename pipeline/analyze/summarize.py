"""Cause summaries for chart events — feature R5.

For recent surges/plunges with matched news, Gemini writes a 2-3 sentence
beginner explanation of *why* the stock moved. Everything else (older events,
newsless events, or when there's no API key / quota is spent) gets a
deterministic rule summary, so the pipeline always produces something.

The LLM budget is global per run (see analyze/llm.py) — free-tier friendly.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from ..config import LLM_RECENT_DAYS
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
    """Populate each event with headline/explain/sentiment/confidence.

    Recent events with news are sent to Gemini (subject to the global budget);
    the rest get a rule summary.
    """
    # Candidates for the LLM: recent + has news, most severe first.
    candidates = sorted(
        [e for e in events if e.get("news") and _is_recent(e)],
        key=lambda e: (e["severity"], len(e["news"])),
        reverse=True,
    )
    items = [
        {
            "id": e["id"], "name": ticker["name"], "code": ticker["code"],
            "market": ticker["market"], "date": e["date"], "changePct": e["changePct"],
            "volumeRatio": e.get("volumeRatio"),
            "news": [n["title"] for n in e["news"][:5]],
        }
        for e in candidates
    ]
    results = llm.explain_events(items) if items else {}

    llm_done = rule_done = 0
    for event in events:
        got = results.get(event["id"])
        if got:
            event.update({
                "headline": T.truncate(str(got.get("headline", "")), 30) or label_for(event),
                "explain": str(got.get("explain", "")).strip(),
                "sentiment": got.get("sentiment", "neutral"),
                "confidence": got.get("confidence", "medium"),
                "tags": [str(t) for t in (got.get("tags") or [])][:5],
                "source": "llm",
            })
            if event["explain"]:
                llm_done += 1
                continue
        _rule_explain(ticker, event)
        rule_done += 1

    if events and llm_done:
        log.info(f"  {ticker['code']}: {llm_done} llm / {rule_done} rule summaries")
    return events


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
