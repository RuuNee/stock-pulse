"""Pre-market brief builder (schema §6).

Turns the freshly built site data into a single brief object per market. The
same object powers both the web brief card and the Telegram message, so the
two can never drift. The 3-line summary is LLM-written when a key is available,
rule-composed otherwise.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from ..analyze import llm
from ..analyze.technical import DISCLAIMER as _TA_DISCLAIMER
from ..config import BRIEF_KEEP_DAYS, SITE_URL, TA_BRIEF_PICKS
from ..util import io
from ..util import text as T
from ..util.dates import iso, next_session_date, now_utc
from ..config import DATA_DIR

_DISCLAIMER = "본 브리핑은 공개된 뉴스를 정리한 정보이며 투자 권유가 아닙니다."

_BULLISH = ("strongBuy", "buy")
_BEARISH = ("strongSell", "sell")


def build_brief(market: str, site: dict) -> dict:
    overview = site["overview"]
    news = [n for n in site["news"] if n.get("market") in (market, "GLOBAL")]
    news.sort(key=lambda n: n.get("importance", 0), reverse=True)

    session_date = next_session_date(market)
    mood = overview["marketMood"].get(market, {})
    snapshot = _snapshot(market, overview["indices"])
    top_news = [_top_news(n) for n in news[:6]]
    chart_signals = _chart_signals(market, site["tickers"])
    watchlist = _watchlist(market, overview["movers"], site["tickers"], site)
    headline, three = _summary(market, snapshot, top_news, mood, chart_signals)

    return {
        "market": market,
        "date": session_date.isoformat(),
        "generatedAt": iso(now_utc()),
        "headline": headline,
        "threeLines": three,
        "mood": {k: mood.get(k) for k in ("score", "label", "color")},
        "marketSnapshot": snapshot,
        "topNews": top_news,
        "chartSignals": chart_signals,
        "watchlistMoves": watchlist,
        "calendar": [],  # reserved; economic-calendar source is a future spec
        "disclaimer": _DISCLAIMER,
        "siteUrl": SITE_URL,
    }


def write_brief(brief: dict) -> None:
    market = brief["market"]
    io.write_json(DATA_DIR / "brief" / f"latest-{market}.json", brief)
    io.write_json(DATA_DIR / "brief" / f"{brief['date']}-{market}.json", brief, quiet=True)
    prune_briefs(market)


def prune_briefs(market: str, *, data_dir: Path | None = None,
                 today: date | None = None) -> list[Path]:
    """오래된 날짜별 브리핑 파일을 지운다. 지운 경로를 돌려준다.

    파일 하나하나는 작지만 시장당 하루 1개씩 무한히 쌓인다. 화면은 이 파일을
    읽지 않고(`latest-*.json` 만 읽는다) 게이트도 이번 세션 것만 본다.

    기준일은 "오늘"이지 방금 쓴 브리핑의 날짜가 아니다. 브리핑 날짜는 *다음*
    세션(=미래)이라, 그걸 기준으로 잡으면 보관 창이 하루씩 밀린다.
    """
    root = (data_dir or DATA_DIR) / "brief"
    cutoff = (today or now_utc().date()) - timedelta(days=BRIEF_KEEP_DAYS)
    removed = []
    for path in sorted(root.glob(f"*-{market}.json")):
        stamp = path.name[:-len(f"-{market}.json")]
        try:
            day = date.fromisoformat(stamp)
        except ValueError:
            continue  # latest-KR.json 처럼 날짜가 아닌 이름은 건드리지 않는다
        if day < cutoff:
            path.unlink()
            removed.append(path)
    if removed:
        print(f"  브리핑 보관 정리: {len(removed)}개 삭제 (>{BRIEF_KEEP_DAYS}일)")
    return removed


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
        "titleKo": n.get("titleKo"),
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


def _chart_signals(market: str, tickers: list[dict]) -> dict:
    """차트 분석 결과를 시장 단위로 모은다 (schema §6).

    종목 파일을 다시 열지 않는다 — `tickers/index.json` 항목에 이미 압축본이
    실려 있어서, 브리핑 전용 재계산이 필요 없다.
    """
    rows = [t for t in tickers
            if t.get("market") == market and isinstance(t.get("analysis"), dict)]
    if not rows:
        return {"asOf": None, "counts": {"bullish": 0, "neutral": 0, "bearish": 0},
                "bullish": [], "bearish": [], "note": _TA_DISCLAIMER}

    def bucket(t: dict) -> str:
        sig = t["analysis"].get("signal")
        return "bullish" if sig in _BULLISH else "bearish" if sig in _BEARISH else "neutral"

    counts = {"bullish": 0, "neutral": 0, "bearish": 0}
    for t in rows:
        counts[bucket(t)] += 1

    ups = sorted((t for t in rows if bucket(t) == "bullish"),
                 key=lambda t: t["analysis"]["score"], reverse=True)
    downs = sorted((t for t in rows if bucket(t) == "bearish"),
                   key=lambda t: t["analysis"]["score"])
    dates = [t["analysis"].get("date") for t in rows if t["analysis"].get("date")]

    return {
        "asOf": max(dates) if dates else None,
        "counts": counts,
        "bullish": [_signal_ref(t) for t in ups[:TA_BRIEF_PICKS]],
        "bearish": [_signal_ref(t) for t in downs[:TA_BRIEF_PICKS]],
        "note": _TA_DISCLAIMER,
    }


def _signal_ref(t: dict) -> dict:
    a = t["analysis"]
    return {
        "code": t["code"], "name": t["name"], "market": t["market"],
        "changePct": t.get("changePct"),
        "score": a["score"], "signal": a["signal"], "label": a["label"],
        "action": a["action"], "actionEmoji": a["actionEmoji"],
        "actionLabel": a["actionLabel"], "headline": a["headline"],
    }


def _watchlist(market, movers, tickers, site) -> list[dict]:
    picks = (movers.get(market, {}).get("up", [])[:3]
             + movers.get(market, {}).get("down", [])[:2])
    by_code = {t["code"]: t for t in tickers if t.get("market") == market}
    out = []
    for m in picks:
        note = _latest_event_note(m["code"], m["market"])
        analysis = (by_code.get(m["code"]) or {}).get("analysis")
        out.append({"code": m["code"], "name": m["name"],
                    "changePct": m["changePct"], "note": note,
                    "signal": (analysis or {}).get("actionLabel"),
                    "signalEmoji": (analysis or {}).get("actionEmoji")})
    return out


def _latest_event_note(code: str, market: str) -> str | None:
    data = io.read_json(DATA_DIR / "tickers" / market / f"{code}.json")
    if not data or not data.get("events"):
        return None
    return data["events"][0].get("headline")


def _summary(market, snapshot, top_news, mood, chart_signals=None):
    label = "국장" if market == "KR" else "미장"
    snap = "\n".join(f"- {s['name']}: {s['value']} ({s['changePct']:+.2f}%)"
                     for s in snapshot if s.get("changePct") is not None)
    heads = "\n".join(f"- {n['title']}" for n in top_news[:6])
    result = llm.brief_summary(label, snap, heads, mood.get("label", "중립"),
                               _tech_line(chart_signals))
    if result:
        return result
    return _rule_summary(label, snapshot, top_news, mood, chart_signals)


def _tech_line(chart_signals) -> str:
    """차트 분석 요약 한 줄. LLM 프롬프트와 규칙 요약이 같은 문장을 쓴다."""
    if not chart_signals or not chart_signals.get("counts"):
        return ""
    c = chart_signals["counts"]
    total = c["bullish"] + c["neutral"] + c["bearish"]
    if not total:
        return ""
    line = (f"차트 지표 기준으로 추적 종목 {total}개 중 매수 우위 {c['bullish']}개, "
            f"매도 우위 {c['bearish']}개입니다.")
    lead = chart_signals.get("bullish") or []
    if lead:
        line += f" 가장 강한 신호는 {lead[0]['name']}({lead[0]['actionLabel']})입니다."
    return line


def _rule_summary(label, snapshot, top_news, mood, chart_signals=None):
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
    tech = _tech_line(chart_signals)
    if tech:
        lines.append(tech)
    while len(lines) < 3:
        lines.append("특별한 대형 이슈 없이 무난하게 출발할 것으로 보입니다.")
    return headline, lines[:3]
