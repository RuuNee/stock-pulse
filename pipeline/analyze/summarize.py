"""LLM-backed cause summaries for chart events — the heart of feature R5.

For each detected surge/plunge, Claude reads the matched news and writes a 2-3
sentence, beginner-friendly explanation of *why* the stock moved that day. When
no API key is present (or a call fails) we fall back to a rule-based summary so
the pipeline always produces something.

Synchronous Messages API — not Batches — because the brief is time-boxed to the
pre-market window and a batch can take up to 24h. Model is Haiku 4.5 for cost;
raise LLM_MAX_EVENTS_PER_RUN in config for wider coverage.
"""

from __future__ import annotations

from ..config import (
    LLM_MAX_EVENTS_PER_RUN,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    anthropic_key,
)
from ..util import log
from ..util import text as T
from .events import label_for

_EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},        # <=30 chars, marker label
        "explain": {"type": "string"},          # 2-3 sentences, 존댓말
        "sentiment": {"type": "string", "enum": ["positive", "negative", "neutral"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "explain", "sentiment", "confidence", "tags"],
    "additionalProperties": False,
}

_SYSTEM = (
    "당신은 주식 초보자를 위한 한국어 시장 해설가입니다. "
    "특정 종목이 특정 날짜에 왜 움직였는지, 그날의 뉴스를 근거로 설명합니다.\n"
    "규칙:\n"
    "- 2~3문장, 존댓말, 쉬운 말. 전문용어를 쓰면 그 자리에서 풀어 설명합니다.\n"
    "- 뉴스에 명확한 원인이 없으면 단정하지 말고 '~로 보입니다' 식으로 표현합니다.\n"
    "- 매수/매도 의견, 목표가, 투자 권유는 절대 하지 않습니다.\n"
    "- headline은 30자 이내 핵심 요약입니다.\n"
    "- 근거 뉴스가 약하면 confidence를 low로 둡니다."
)


def _client():
    key = anthropic_key()
    if not key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=key)
    except Exception as exc:  # pragma: no cover - import/env guard
        log.warn(f"anthropic client unavailable: {exc}")
        return None


def summarize_events(ticker: dict, events: list[dict]) -> list[dict]:
    """Populate each event with headline/explain/sentiment/confidence.

    Only the top ``LLM_MAX_EVENTS_PER_RUN`` most-severe events with news get an
    LLM call; the rest (and everything, if there's no key) get a rule summary.
    """
    client = _client()
    budget = LLM_MAX_EVENTS_PER_RUN if client else 0

    # Prioritise: high severity + has news first.
    ranked = sorted(
        events,
        key=lambda e: (e["severity"], len(e.get("news", []))),
        reverse=True,
    )
    llm_ids = {e["id"] for e in ranked[:budget] if e.get("news")}

    llm_done = rule_done = 0
    for event in events:
        if event["id"] in llm_ids:
            result = _llm_explain(client, ticker, event)
            if result:
                event.update(result)
                event["source"] = "llm"
                llm_done += 1
                continue
        _rule_explain(ticker, event)
        rule_done += 1

    if events:
        log.info(f"  {ticker['code']}: {llm_done} llm / {rule_done} rule summaries")
    return events


def _llm_explain(client, ticker: dict, event: dict) -> dict | None:
    news_lines = "\n".join(
        f"- ({n.get('source', '?')}) {n['title']}"
        for n in event.get("news", [])[:5]
    )
    direction = "상승" if event["changePct"] > 0 else "하락"
    prompt = (
        f"종목: {ticker['name']} ({ticker['code']}, {ticker['market']})\n"
        f"날짜: {event['date']}\n"
        f"그날 주가: {event['changePct']:+.2f}% {direction}"
        f" (거래량 평소 대비 {event.get('volumeRatio') or '?'}배)\n\n"
        f"그 무렵 관련 뉴스:\n{news_lines or '- (관련 뉴스 없음)'}\n\n"
        "이 종목이 이 날 왜 이렇게 움직였는지 초보자에게 설명해 주세요."
    )

    try:
        resp = client.messages.create(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": _EXPLAIN_SCHEMA}},
        )
    except Exception as exc:
        log.warn(f"llm call failed ({ticker['code']} {event['date']}): {exc}")
        return None

    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        return None
    import json
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    return {
        "headline": T.truncate(str(data.get("headline", "")), 30),
        "explain": str(data.get("explain", "")).strip(),
        "sentiment": data.get("sentiment", "neutral"),
        "confidence": data.get("confidence", "medium"),
        "tags": [str(t) for t in (data.get("tags") or [])][:5],
    }


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
