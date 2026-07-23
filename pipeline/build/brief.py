"""Pre-market brief builder (schema §6).

Turns the freshly built site data into a single brief object per market. The
same object powers both the web brief card and the Telegram message, so the
two can never drift. The 3-line summary is LLM-written when a key is available,
rule-composed otherwise.
"""

from __future__ import annotations

from ..config import LLM_MODEL, LLM_MAX_TOKENS, SITE_URL, anthropic_key
from ..util import io, log
from ..util import text as T
from ..util.dates import iso, next_session_date, now_utc
from ..config import DATA_DIR

_DISCLAIMER = "본 브리핑은 공개된 뉴스를 정리한 정보이며 투자 권유가 아닙니다."

_THREE_LINE_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "threeLines": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["headline", "threeLines"],
    "additionalProperties": False,
}


def build_brief(market: str, site: dict) -> dict:
    overview = site["overview"]
    news = [n for n in site["news"] if n.get("market") in (market, "GLOBAL")]
    news.sort(key=lambda n: n.get("importance", 0), reverse=True)

    session_date = next_session_date(market)
    mood = overview["marketMood"].get(market, {})
    snapshot = _snapshot(market, overview["indices"])
    top_news = [_top_news(n) for n in news[:6]]
    watchlist = _watchlist(market, overview["movers"], site["tickers"], site)
    headline, three = _summary(market, snapshot, top_news, mood)

    return {
        "market": market,
        "date": session_date.isoformat(),
        "generatedAt": iso(now_utc()),
        "headline": headline,
        "threeLines": three,
        "mood": {k: mood.get(k) for k in ("score", "label", "color")},
        "marketSnapshot": snapshot,
        "topNews": top_news,
        "watchlistMoves": watchlist,
        "calendar": [],  # reserved; economic-calendar source is a future spec
        "disclaimer": _DISCLAIMER,
        "siteUrl": SITE_URL,
    }


def write_brief(brief: dict) -> None:
    market = brief["market"]
    io.write_json(DATA_DIR / "brief" / f"latest-{market}.json", brief)
    io.write_json(DATA_DIR / "brief" / f"{brief['date']}-{market}.json", brief, quiet=True)


# --------------------------------------------------------------------------
def _snapshot(market: str, indices: list[dict]) -> list[dict]:
    keys = (["US500", "IXIC", "USD/KRW", "^TNX"] if market == "KR"
            else ["US500", "IXIC", "VIX", "CL=F"])
    out = []
    for k in keys:
        idx = next((i for i in indices if i["key"] == k), None)
        if idx:
            out.append({"name": idx["name"], "value": idx["value"],
                        "changePct": idx["changePct"], "unit": idx["unit"]})
    return out


def _top_news(n: dict) -> dict:
    return {
        "title": n["title"],
        "url": n["url"],
        "source": n.get("source"),
        "why": _why(n),
        "tickers": [{"code": t["code"], "name": t["name"]}
                    for t in n.get("tickers", [])[:3]],
        "importance": n.get("importance"),
    }


def _why(n: dict) -> str:
    """One-line beginner rationale. Keyword-based; cheap and deterministic."""
    text = f"{n.get('title', '')} {n.get('summary', '')}"
    rules = [
        (("금리", "FOMC", "연준", "rate", "fed"),
         "금리가 오르면 빌린 돈으로 성장하는 기술주에 부담이 됩니다."),
        (("환율", "원달러", "달러"),
         "환율이 오르면 외국인이 한국 주식을 팔 유인이 커집니다."),
        (("실적", "영업이익", "어닝", "earnings", "guidance"),
         "실적은 주가를 움직이는 가장 직접적인 재료입니다."),
        (("관세", "무역", "tariff", "trade"),
         "무역·관세 이슈는 수출 기업 실적에 영향을 줍니다."),
        (("반도체", "HBM", "chip", "AI"),
         "반도체는 국내 증시 시가총액 비중이 커 지수 전체에 영향을 줍니다."),
    ]
    for keys, why in rules:
        if any(k in text for k in keys):
            return why
    if n.get("tickers"):
        return f"{n['tickers'][0]['name']} 관련 소식으로 해당 종목에 영향을 줄 수 있습니다."
    return "오늘 시장 심리에 영향을 줄 수 있는 소식입니다."


def _watchlist(market, movers, tickers, site) -> list[dict]:
    picks = (movers.get(market, {}).get("up", [])[:3]
             + movers.get(market, {}).get("down", [])[:2])
    out = []
    for m in picks:
        note = _latest_event_note(m["code"], m["market"])
        out.append({"code": m["code"], "name": m["name"],
                    "changePct": m["changePct"], "note": note})
    return out


def _latest_event_note(code: str, market: str) -> str | None:
    data = io.read_json(DATA_DIR / "tickers" / market / f"{code}.json")
    if not data or not data.get("events"):
        return None
    return data["events"][0].get("headline")


def _summary(market, snapshot, top_news, mood):
    label = "국장" if market == "KR" else "미장"
    client = _client()
    if client:
        result = _llm_summary(client, label, snapshot, top_news, mood)
        if result:
            return result
    return _rule_summary(label, snapshot, top_news, mood)


def _client():
    key = anthropic_key()
    if not key:
        return None
    try:
        import anthropic
        return anthropic.Anthropic(api_key=key)
    except Exception:
        return None


def _llm_summary(client, label, snapshot, top_news, mood):
    snap = "\n".join(f"- {s['name']}: {s['value']} ({s['changePct']:+.2f}%)"
                     for s in snapshot if s.get("changePct") is not None)
    heads = "\n".join(f"- {n['title']}" for n in top_news[:6])
    prompt = (
        f"{label} 개장 전 브리핑입니다. 시장 분위기: {mood.get('label', '중립')}.\n\n"
        f"간밤/전일 지표:\n{snap}\n\n오늘 주요 뉴스:\n{heads}\n\n"
        "초보 투자자가 오늘 시장을 이해하도록 headline 1개와 3줄 요약을 만들어 주세요.\n"
        "- headline: 오늘의 핵심을 한 문장으로.\n"
        "- threeLines: 각 항목 한 문장, 존댓말, 쉬운 말. 투자 권유 금지."
    )
    try:
        resp = client.messages.create(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            system="당신은 주식 초보자를 위한 한국어 시장 브리핑 작성자입니다. 사실만 전달하고 투자 권유는 하지 않습니다.",
            messages=[{"role": "user", "content": prompt}],
            output_config={"format": {"type": "json_schema", "schema": _THREE_LINE_SCHEMA}},
        )
    except Exception as exc:
        log.warn(f"brief llm failed ({label}): {exc}")
        return None
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        return None
    import json
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    lines = [str(x).strip() for x in (data.get("threeLines") or [])][:3]
    if not lines:
        return None
    return str(data.get("headline", "")).strip(), lines


def _rule_summary(label, snapshot, top_news, mood):
    headline = f"{label} 개장 전 점검 · 시장 분위기 {mood.get('label', '중립')}"
    lines = []
    us = next((s for s in snapshot if s["name"] in ("S&P 500", "나스닥")), None)
    if us and us.get("changePct") is not None:
        move = "올랐습니다" if us["changePct"] >= 0 else "내렸습니다"
        lines.append(f"간밤 {us['name']}가 {abs(us['changePct']):.2f}% {move}.")
    fx = next((s for s in snapshot if s["name"] == "원달러"), None)
    if fx and fx.get("value"):
        lines.append(f"원달러 환율은 {fx['value']:,.0f}원 수준입니다.")
    if top_news:
        lines.append(f"오늘 주목할 뉴스: {T.truncate(top_news[0]['title'], 40)}.")
    while len(lines) < 3:
        lines.append("특별한 대형 이슈 없이 무난하게 출발할 것으로 보입니다.")
    return headline, lines[:3]
