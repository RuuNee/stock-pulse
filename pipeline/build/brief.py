"""Pre-market brief builder (schema §6).

Turns the freshly built site data into a single brief object per market. The
same object powers both the web brief card and the Telegram message, so the
two can never drift.

2026-10-15 개편 — 사용자 신고 여섯 가지가 출발점이다 (99-스펙변경이력).

* "오늘 꼭 알아야 할 3가지"가 매일 같았다. 3줄 중 2줄이 틀로 고정돼 있었다 —
  간밤 지수 등락(바로 아래 지표 칸과 같은 내용)과 "차트 지표 기준 매수 우위 N개".
* 코스피 -7.6% 날 아침 브리핑이 "중립 47점"이었다. 점수식이 전날 코스피만 보고
  밤사이 미국 반도체·한국 ETF 급락을 안 봤다 → `mood.outlook`.
* 왜 움직였는지 설명이 없었다. 3줄 요약에 헤드라인 6개만 넘겼으니 쓸 재료가
  없었다 → 지표·수급·시황 기사·후보 기사를 다 넘기고 해설 4단락을 받는다.
* 주요 뉴스가 같은 사건 3건이었고 "💡" 한 줄은 키워드 규칙이라 엉뚱했다
  ("양자역학의 세계" → "금리가 오르면…") → `analyze/curate.py` + LLM 이 고르고 쓴다.

LLM 이 없거나 실패해도 브리핑은 나간다 — 규칙 요약 + 규칙 선별로.
"""

from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta

from ..analyze import curate, llm, mood
from ..analyze.technical import DISCLAIMER as _TA_DISCLAIMER
from ..collect import calendar as calendar_mod
from ..collect import naver as naver_mod
from ..collect import news as news_mod
from ..collect import prices
from ..config import (
    BRIEF_KEEP_DAYS,
    BRIEF_KR_LEADERS,
    BRIEF_NEWS_FALLBACK_HOURS,
    BRIEF_NEWS_TICKER_MIN,
    BRIEF_NEWS_TOTAL,
    CALENDAR_EARNINGS,
    CALENDAR_MAX_ITEMS,
    DATA_DIR,
    KR_LINKED_US,
    KST,
    ET,
    SITE_URL,
    TA_BRIEF_PICKS,
    US_BELLWETHERS,
    WRAP_BIG_MOVE_PCT,
    WRAP_PER_QUERY,
    WRAP_QUERIES,
    WRAP_WHY_QUERIES,
)
from ..util import io, log
from ..util import text as T
from ..util.dates import (
    WEEKDAY_KR, iso, next_session_date, now_kst, now_utc, parse_iso, session_closed,
)

_DISCLAIMER = "본 브리핑은 공개된 뉴스를 정리한 정보이며 투자 권유가 아닙니다."

_BULLISH = ("strongBuy", "buy")
_BEARISH = ("strongSell", "sell")

# 시장별 지표 칸. 국장 브리핑은 전날 국장 마감 + 밤사이 미국, 미장 브리핑은 전날
# 미장 마감 + 오늘 아시아. 예전 국장 브리핑에는 코스피가 아예 없었다.
_SNAPSHOT_KEYS = {
    "KR": ["KS11", "KQ11", "US500", "IXIC", "^SOX", "USD/KRW", "^TNX", "VIX"],
    "US": ["US500", "IXIC", "DJI", "^SOX", "VIX", "^TNX", "CL=F", "KS11"],
    # 장 마감 브리핑: 오늘 국장 + 지금 미국 선물. 어젯밤 미국 지수는 아침 브리핑에서 봤다.
    "KR-close": ["KS11", "KQ11", "USD/KRW"],
}
_FUTURES = (("ES=F", "S&P 500 선물"), ("NQ=F", "나스닥 100 선물"))

_SECTIONS = {
    "KR": ("어제 국장", "간밤 미국", "흐름 읽기", "앞으로 볼 것"),
    "US": ("어제 미장", "밤사이 세계", "흐름 읽기", "앞으로 볼 것"),
    "KR-close": ("오늘 국장", "왜 움직였나", "흐름 읽기", "내일 볼 것"),
}
CLOSE_NEWS_TOTAL = 3        # 마감 브리핑은 추가로 받는 메시지라 짧게


def build_brief(market: str, site: dict, *, late: bool = False) -> dict:
    overview = site["overview"]
    indices = overview["indices"]
    session_date = next_session_date(market)
    prev = previous_brief(market, session_date)

    futures = _futures() if market == "US" else {}
    breadth = (overview.get("breadth") or {}).get(market)
    outlook = mood.outlook(market, indices, futures=futures, breadth=breadth)
    snapshot = _snapshot(market, indices, futures)
    flows = naver_mod.fetch_kr_flows() if market == "KR" else None

    since = news_since(prev)
    sent = {n.get("url") for n in (prev or {}).get("topNews", []) if n.get("url")}
    cands = curate.candidates(site["news"], market, since=since, exclude_urls=sent)
    wrap = _market_wrap(market, indices, since)
    chart_signals = _chart_signals(market, site["tickers"])
    watchlist = _watchlist(market, overview["movers"], site["tickers"], site)
    calendar = _calendar(market, session_date, site["tickers"])

    ctx = {
        "market": market, "session": session_date, "outlook": outlook,
        "indices": indices, "futures": futures, "flows": flows,
        "leaders": _leaders(market, site["tickers"]), "movers": watchlist,
        "wrap": wrap, "candidates": cands, "calendar": calendar, "prev": prev,
        "upcoming": _upcoming(market, session_date),
        "closePrev": previous_close_brief(market, session_date, prev),
    }
    commentary = _commentary(ctx)
    if commentary:
        headline, three, analysis, picks = commentary
    else:
        headline, three = _rule_summary(ctx)
        analysis = None
        picks = [(n, None, None) for n in _home_first(_pick_news(
            _home_first(cands), key="briefScore"))]

    return {
        "market": market,
        "date": session_date.isoformat(),
        "generatedAt": iso(now_utc()),
        # 발송 창을 놓쳐 개장 뒤에 나가는 브리핑. 텔레그램 렌더러가 경고 줄을
        # 붙이고, 화면도 "장전"이라고 우기지 않게 하려고 파일에 남긴다.
        "late": late,
        "headline": headline,
        "threeLines": three,
        "mood": {k: outlook.get(k) for k in ("score", "label", "color", "kind", "reason")},
        "analysis": analysis,
        "marketSnapshot": snapshot,
        "flows": flows,
        "topNews": [_top_news(n, why=why, title_ko=ko) for n, why, ko in picks],
        # 해설이 없을 때(LLM 실패) 원인을 대신 짚어 주는 시황 기사 제목들.
        "wrapHeadlines": [{"title": w["title"], "url": w["url"], "source": w.get("source")}
                          for w in wrap[:5]],
        "chartSignals": chart_signals,
        "watchlistMoves": watchlist,
        "calendar": calendar,
        "disclaimer": _DISCLAIMER,
        "siteUrl": SITE_URL,
    }


def write_brief(brief: dict) -> None:
    market = brief["market"]
    tag = f"{market}-close" if brief.get("kind") == "close" else market
    io.write_json(DATA_DIR / "brief" / f"latest-{tag}.json", brief)
    io.write_json(DATA_DIR / "brief" / f"{brief['date']}-{tag}.json", brief, quiet=True)
    prune_briefs(market)


def prune_briefs(market: str, *, data_dir=None, today: date | None = None) -> list:
    """오래된 날짜별 브리핑 파일을 지운다. 지운 경로를 돌려준다.

    파일 하나하나는 작지만 시장당 하루 1개씩 무한히 쌓인다. 화면은 이 파일을
    읽지 않고(`latest-*.json` 만 읽는다) 게이트도 이번 세션 것만 본다.

    기준일은 "오늘"이지 방금 쓴 브리핑의 날짜가 아니다. 브리핑 날짜는 *다음*
    세션(=미래)이라, 그걸 기준으로 잡으면 보관 창이 하루씩 밀린다.
    """
    root = (data_dir or DATA_DIR) / "brief"
    cutoff = (today or now_utc().date()) - timedelta(days=BRIEF_KEEP_DAYS)
    removed = []
    paths = sorted(root.glob(f"*-{market}.json")) + sorted(root.glob(f"*-{market}-close.json"))
    for path in paths:
        try:
            day = date.fromisoformat(path.name[:10])
        except ValueError:
            continue  # latest-KR.json 처럼 날짜가 아닌 이름은 건드리지 않는다
        if day < cutoff:
            path.unlink()
            removed.append(path)
    if removed:
        print(f"  브리핑 보관 정리: {len(removed)}개 삭제 (>{BRIEF_KEEP_DAYS}일)")
    return removed


def previous_brief(market: str, session_date: date, *, data_dir=None) -> dict | None:
    """이번 세션 직전에 나간 브리핑. 같은 날 다시 만드는 경우(리허설)는 건너뛴다."""
    root = (data_dir or DATA_DIR) / "brief"
    for path in sorted(root.glob(f"????-??-??-{market}.json"), reverse=True):
        if path.name[:10] < session_date.isoformat():
            return io.read_json(path)
    return None


def previous_close_brief(market: str, session_date: date, prev: dict | None = None,
                         *, data_dir=None) -> dict | None:
    """직전 거래일에 나간 장 마감 브리핑 (큰 변동일에만 있다). 아침 브리핑이 반복을 피하는 데 쓴다.

    직전 장전 브리핑보다 오래된 것은 쓰지 않는다 — 사흘 전 급락 설명을 "어제"로 읽게 된다.
    """
    root = (data_dir or DATA_DIR) / "brief"
    floor = (prev or {}).get("date") or ""
    for path in sorted(root.glob(f"????-??-??-{market}-close.json"), reverse=True):
        day = path.name[:10]
        if day < session_date.isoformat():
            return io.read_json(path) if day >= floor else None
    return None


def news_since(prev: dict | None, now: datetime | None = None) -> datetime:
    """뉴스 창의 시작 — 직전 브리핑 2시간 전부터. 직전 브리핑이 없으면 고정 시간."""
    now = now or now_utc()
    started = parse_iso((prev or {}).get("generatedAt"))
    if started is None or started > now:
        return now - timedelta(hours=BRIEF_NEWS_FALLBACK_HOURS)
    # 연휴 뒤 첫 브리핑이라도 피드 보관 기간(3일)보다 길게 볼 이유는 없다.
    return max(started - timedelta(hours=2), now - timedelta(days=4))


# --------------------------------------------------------------------------
# 장 마감 브리핑 (큰 변동일에만 — gate.close_mode 가 판정)
# --------------------------------------------------------------------------
def build_close_brief(market: str, site: dict) -> dict:
    """국장 마감 브리핑. 장전 브리핑과 같은 꼴(`kind: "close"`)이라 텔레그램·사이트가 같이 쓴다.

    2026-10-15 코스피 -7.6% 날 "급락 이유가 뉴스에 없다"는 신고의 당일 답이다. 장전
    브리핑만으로는 다음 날 아침에야 설명됐다. 매일 보내면 하루 세 통이 되므로 코스피가
    ±2%(config.CLOSE_BRIEF_MIN_MOVE) 넘게 움직인 날에만 게이트가 열어 준다.

    지수 숫자는 네이버 마감값으로 덮는다 — FinanceDataReader 는 마감 직후 몇 시간 동안
    잠정값을 줬다 (10-15: 5,535.43 vs 공식 5,554.22).
    """
    session = now_kst().date()
    overview = site["overview"]
    indices = _with_today_close(overview["indices"], naver_mod.fetch_kr_indices(), session)
    morning = io.read_json(DATA_DIR / "brief" / f"{session.isoformat()}-{market}.json")
    futures = _futures()

    since = news_since(morning)
    sent = {n.get("url") for n in (morning or {}).get("topNews", []) if n.get("url")}
    cands = curate.candidates(site["news"], market, since=since, exclude_urls=sent)
    wrap = _market_wrap(market, indices, since)
    leaders = naver_mod.fetch_kr_leaders(8)
    flows = naver_mod.fetch_kr_flows()
    calendar = _calendar(market, session)

    ctx = {
        "market": market, "variant": f"{market}-close", "session": session,
        "outlook": None, "morning": morning, "indices": indices, "futures": futures,
        "flows": flows, "leaders": {"KR": leaders, "US": []}, "movers": [],
        "wrap": wrap, "candidates": cands, "calendar": calendar, "prev": morning,
        "upcoming": _upcoming(market, session), "nNews": CLOSE_NEWS_TOTAL,
    }
    commentary = _commentary(ctx)
    if commentary:
        headline, three, analysis, picks = commentary
    else:
        headline, three = _rule_close_summary(ctx)
        analysis = None
        picks = [(n, None, None) for n in _home_first(_pick_news(
            _home_first(cands), key="briefScore", total=CLOSE_NEWS_TOTAL))]

    return {
        "market": market,
        "kind": "close",
        "date": session.isoformat(),
        "generatedAt": iso(now_utc()),
        "late": False,
        "headline": headline,
        "threeLines": three,
        "mood": {},
        "analysis": analysis,
        "marketSnapshot": _snapshot(f"{market}-close", indices, futures),
        "flows": flows,
        "leaders": leaders[:6],
        "topNews": [_top_news(n, why=why, title_ko=ko) for n, why, ko in picks],
        "wrapHeadlines": [{"title": w["title"], "url": w["url"], "source": w.get("source")}
                          for w in wrap[:5]],
        "chartSignals": None,
        "watchlistMoves": [],
        "calendar": calendar,
        "disclaimer": _DISCLAIMER,
        "siteUrl": SITE_URL,
    }


def _with_today_close(indices: list[dict], naver: dict | None, session: date) -> list[dict]:
    """코스피·코스닥 항목을 네이버의 오늘 마감값으로 바꾼다. 추세(5일·52주)는 이어서 계산한다.

    오늘 마감이 확정되지 않았으면(장중·다른 날짜) 손대지 않는다.
    """
    out = []
    for i in indices:
        key = {"KS11": "KOSPI", "KQ11": "KOSDAQ"}.get(i["key"])
        row = (naver or {}).get(key) if key else None
        if not row or not row.get("closed") or row.get("date") != session.isoformat():
            out.append(i)
            continue
        fresh = dict(i, value=row["close"], change=row.get("change"),
                     changePct=row["changePct"], date=row["date"])
        if (i.get("date") or "") < row["date"]:
            # 저장된 항목은 어제 마감 기준이다. spark(최근 30종가)로 5·20일 등락을 다시 잡는다.
            closes = list(i.get("spark") or []) + [row["close"]]
            for k, n in (("change5d", 5), ("change20d", 20)):
                fresh[k] = (round((closes[-1] / closes[-1 - n] - 1) * 100, 2)
                            if len(closes) > n and closes[-1 - n] else None)
            if i.get("fromHigh52w") is not None and i.get("value"):
                high = max(i["value"] / (1 + i["fromHigh52w"] / 100), row["close"])
                fresh["fromHigh52w"] = round((row["close"] / high - 1) * 100, 2)
        out.append(fresh)
    return out


def _rule_close_summary(ctx: dict) -> tuple[str, list[str]]:
    find = {i["key"]: i for i in ctx["indices"]}
    k, q = find.get("KS11"), find.get("KQ11")
    lines: list[str] = []
    headline = "국장 마감 — 큰 변동일"
    if k and k.get("changePct") is not None:
        move = "올라" if k["changePct"] >= 0 else "내려"
        headline = f"코스피 {k['changePct']:+.2f}% 마감 — 큰 변동일"
        line = f"오늘 코스피는 {abs(k['changePct']):.2f}% {move} {k['value']:,.2f}에 마감했습니다"
        if q and q.get("changePct") is not None:
            line += f" (코스닥 {q['changePct']:+.2f}%)"
        f = (ctx.get("flows") or {}).get("KOSPI")
        if f and f.get("foreign"):
            side = "순매수" if f["foreign"] > 0 else "순매도"
            line += f". 외국인은 {naver_mod.eok_label(abs(f['foreign'])).lstrip('+')}원어치를 {side}했습니다"
        lines.append(line + ".")
    leaders = [r for r in (ctx.get("leaders") or {}).get("KR", []) if r.get("changePct") is not None]
    if leaders:
        lines.append("시가총액 상위: " + ", ".join(f"{r['name']} {r['changePct']:+.1f}%"
                                              for r in leaders[:4]) + ".")
    for w in (ctx.get("wrap") or []) + (ctx.get("candidates") or []):
        if len(lines) >= 3:
            break
        lines.append(f"시황: {T.truncate(w['title'], 70)}")
    return headline, lines[:3]


# --------------------------------------------------------------------------
# 지표
# --------------------------------------------------------------------------
def _snapshot(market: str, indices: list[dict], futures: dict | None = None) -> list[dict]:
    out = []
    for k in _SNAPSHOT_KEYS[market]:
        idx = next((i for i in indices if i["key"] == k), None)
        if idx:
            out.append({"key": k, "name": idx["name"], "value": idx["value"],
                        "change": idx.get("change"), "changePct": idx["changePct"],
                        "unit": idx["unit"], "date": idx.get("date")})
    for key, f in (futures or {}).items():
        if f.get("live"):
            out.append({"key": key, "name": f"{f['name']}(실시간)", "value": f["value"],
                        "change": None, "changePct": f["changePct"], "unit": "pt",
                        "date": f.get("date")})
    return out


def _futures() -> dict:
    """미국 지수 선물 — 미장 개장 전 실시간 방향. 지수 카드와 달리 진행 중인 봉을 쓴다.

    사이트의 지수 카드는 "마감 기준"이 원칙이라 여기서만 받는다. `live` 는 오늘 세션이
    아직 진행 중인 봉인지 — 아니면(주말·휴장) 전망 점수에 넣지 않는다.
    """
    out = {}
    for key, name in _FUTURES:
        try:
            df = prices.fetch_ohlcv(key, years=1)
        except Exception as exc:
            log.warn(f"futures {key} skipped: {exc}")
            continue
        if df is None or len(df) < 2:
            continue
        q = prices.quote_from(df)
        live = not session_closed("US", df.index[-1].date())
        out[key] = {"name": name, "value": q.get("close"), "changePct": q.get("changePct"),
                    "date": q.get("date"), "live": live}
    return out


def _leaders(market: str, tickers: list[dict]) -> dict:
    """해설에 넘길 대표 종목 등락 — 국장 시총 상위 + 미국 대표주."""
    kr = sorted((t for t in tickers if t.get("market") == "KR" and t.get("marcap")
                 and t.get("exchange") != "ETF"), key=lambda t: -t["marcap"])
    us_by_code = {t["code"]: t for t in tickers if t.get("market") == "US"}
    us = [us_by_code[c] for c in US_BELLWETHERS if c in us_by_code]
    pick = lambda rows: [{"name": t["name"], "changePct": t.get("changePct"),  # noqa: E731
                          "date": t.get("date")} for t in rows]
    return {"KR": pick(kr[:BRIEF_KR_LEADERS]), "US": pick(us)}


# --------------------------------------------------------------------------
# 시황 기사
# --------------------------------------------------------------------------
def _market_wrap(market: str, indices: list[dict], since: datetime) -> list[dict]:
    queries = list(WRAP_QUERIES.get(market, []))
    keys = ("KS11",) if market == "KR" else ("US500", "IXIC")
    moves = [i.get("changePct") for i in indices if i["key"] in keys and i.get("changePct") is not None]
    if moves:
        big = max(moves, key=abs)
        if abs(big) >= WRAP_BIG_MOVE_PCT:
            why = WRAP_WHY_QUERIES.get((market, "down" if big < 0 else "up"))
            if why:
                queries.append(why)
    hours = (now_utc() - since).total_seconds() / 3600
    days = min(3, max(1, math.ceil(hours / 24)))
    try:
        items = news_mod.fetch_market_wrap(market, queries, days=days, per_query=WRAP_PER_QUERY)
    except Exception as exc:          # 시황 기사가 없어도 브리핑은 나간다
        log.warn(f"market wrap skipped: {exc}")
        return []
    items = [w for w in items if (parse_iso(w.get("publishedAt")) or now_utc()) >= since]
    items.sort(key=lambda w: w.get("publishedAt") or "", reverse=True)
    return items[:25]


# --------------------------------------------------------------------------
# LLM 해설
# --------------------------------------------------------------------------
_INSTRUCT = """당신은 한국 개인투자자에게 매일 시장 브리핑을 쓰는 애널리스트입니다. 독자는 주식 초보지만
"경제가 어떻게 흘러가서 주가가 이렇게 움직이는지"를 이해하고 싶어 합니다.

원칙
- 사실(숫자·사건·발언)은 아래 [자료]에 있는 것만 씁니다. 자료에 없는 수치·사건·발언을 지어내지 마세요.
  금리·환율·물가가 주가에 미치는 일반적인 원리는 설명에 써도 됩니다.
- 원인은 근거와 함께 씁니다("시황 기사들은 ~를 원인으로 꼽습니다", "~라는 분석이 나옵니다"). 근거가 약하면 단정하지 마세요.
- 쉬운 존댓말. 전문용어는 처음 나올 때 괄호로 짧게 풀이합니다. 예: 서킷브레이커(지수가 8% 넘게 빠지면 20분간 거래를 멈추는 장치)
- 매수·매도 권유, 목표가, "지금 사라/팔아라" 같은 문장은 금지입니다. 전망은 조건을 단 시나리오로 씁니다.
- 자료의 꺾쇠 제목([지표], [후보 기사] 등)을 본문에 쓰지 마세요. 독자는 자료를 보지 못합니다.{note}

JSON 하나로만 답하세요:
{{"headline": "오늘 시장을 한 문장으로 (40자 안팎)",
 "threeLines": ["...", "...", "..."],
 "analysis": [{{"title": "{s0}", "body": "..."}}, {{"title": "{s1}", "body": "..."}},
              {{"title": "{s2}", "body": "..."}}, {{"title": "{s3}", "body": "..."}}],
 "news": [{{"id": 후보 번호, "why": "...", "titleKo": "영문 기사일 때만 한국어 제목"}}]}}

threeLines — 오늘 꼭 알아야 할 3가지
- 서로 다른 축에서 하나씩 고르세요: {axes}.
  세 줄이 같은 사건을 말만 바꿔 반복하면 안 됩니다.
- 각 줄은 한 문장으로 "무슨 일이 있었고 → 그래서 오늘 시장에 무슨 의미인지"를 담고, 자료의 구체적인 숫자·이름을 넣습니다.
- 지표 칸에 이미 있는 등락률을 나열만 하는 줄은 금지입니다. 단, 지수 급변 자체가 핵심 사건이면 원인과 함께 쓰세요.
- 차트 신호, 매수·매도 우위 종목 수 이야기는 쓰지 마세요.
- [{prev_label}]와 같은 이야기는 새 진전이 없으면 빼고 다른 주제를 고르세요.

analysis — 시장 해설 (각 2~4문장, "{s2}"는 3~5문장)
- {s0}: {d0}
- {s1}: {d1}
- {s2}: 원인들이 어떻게 이어지는지 인과 사슬로 설명합니다 (예: 미국 물가↑ → 금리 인하 기대↓ → 성장주 부담 → 외국인 반도체 매도 → 코스피 하락).
  기술·산업(AI 투자, 반도체 사이클 등), 정책·외교(관세, 수출통제, 지정학), 금리·환율, 수급(외국인, 신용융자, 연기금 등) 가운데 자료에 근거가 있는 것을 짚으세요.
  하루짜리 사건인지, 며칠째 이어지는 흐름인지도 [지표]의 5일·20일 등락으로 밝혀 주세요.
- {s3}: [예정된 실적 발표]·[다가오는 실적 발표]·기사에 나온 구체적인 일정과 숫자 2~3개(예: 22일 테슬라 실적, 다음 주 ○○ 발표)와,
  그 결과가 어느 쪽이면 시장이 어떻게 반응할 수 있는지를 조건부로 씁니다.
  "연준 발언에 주목해야 합니다" 같은 막연한 문장은 금지입니다. 좋은 재료와 나쁜 재료가 함께 있으면 둘 다 짚으세요.

news — 주요 뉴스 {n}개
- [후보 기사]에서 오늘 시장을 이해하는 데 가장 중요한 {n}개를 중요한 순서로 고르세요. 같은 사건은 하나만, 지역 행사·사회 단신·광고성 기사는 빼세요.
- why: 그 기사가 오늘 투자자에게 왜 중요한지 한 문장 — 제목을 되풀이하지 말고, 그 결과 다음에 무엇이(어떤 업종·종목·지표가)
  어떤 영향을 받을 수 있는지를 씁니다. "실적은 주가에 중요합니다", "투자 심리에 영향을 줄 수 있습니다" 같은 일반론은 금지입니다.
"""

# 미장 브리핑은 한국 시간 밤에 나간다. 리허설에서 "오늘 국내 기술주에 부담"이라고
# 썼는데, 그 시각엔 그날 국장이 이미 끝났다.
_OUTLOOK_RULE = "\n- [오늘 장 전망 점수]와 반대되는 분위기로 쓰지 마세요."
_MARKET_NOTE = {
    "KR": _OUTLOOK_RULE,
    "US": _OUTLOOK_RULE + (
        "\n- 이 브리핑은 한국 시간 밤, 미국장 개장 전에 나갑니다. 그날 국장은 이미 끝났으니 "
        "한국 증시 영향은 '내일 국장'으로 쓰세요. 아시아 증시가 크게 움직였다면 원인과 함께 짚으세요."),
    "KR-close": (
        "\n- 이 브리핑은 국장이 15:30 에 마감한 뒤, 코스피가 ±2% 넘게 움직인 날에만 나갑니다. "
        "오늘 장이 '왜' 그렇게 움직였는지가 핵심입니다."
        "\n- [오늘 아침 브리핑]의 전망과 실제 결과가 크게 달랐다면 장중에 무엇이 달라졌는지 짚으세요."),
}
# 장 마감 브리핑이 나간 다음 날 아침 — 같은 급락 설명을 두 번 읽히지 않게.
_AFTER_CLOSE_NOTE = ("\n- 어제 국장은 [어제 장 마감 브리핑]에서 이미 자세히 설명했습니다. '어제 국장' 단락은 "
                     "2문장 이내로 핵심만 짚고, 밤사이 달라진 점과 오늘 전망에 집중하세요.")
_AXES = {
    "KR": "① 직전 세션의 핵심 사건과 그 원인 ② 밤사이 새로 나온 재료 ③ 오늘 이후를 좌우할 일정·변수",
    "US": "① 직전 세션의 핵심 사건과 그 원인 ② 밤사이 새로 나온 재료 ③ 오늘 이후를 좌우할 일정·변수",
    "KR-close": "① 오늘 지수·주도 종목이 얼마나 움직였는지(수급 포함) ② 그 원인 ③ 내일·다음 주를 좌우할 일정·변수",
}
_PREV_LABEL = {"KR": "어제 브리핑의 3가지", "US": "어제 브리핑의 3가지",
               "KR-close": "오늘 아침 브리핑의 3가지"}

_SECTION_GUIDE = {
    "KR": ("지수가 얼마나, 왜 움직였는지. 수급(외국인·기관·개인)과 주도 업종·종목을 근거로.",
           "미국 증시에서 무슨 일이 있었고 오늘 한국 시장에 어떤 의미인지 (반도체·AI·금리·환율 경로로)."),
    "US": ("미국 지수가 얼마나, 왜 움직였는지. 주도 업종·종목과 금리·물가를 근거로.",
           "오늘 아시아 증시와 미국 선물에서 무슨 일이 있었고 오늘 밤 미국장에 어떤 의미인지."),
    "KR-close": ("오늘 코스피·코스닥이 얼마나 움직였고 무엇이 주도했는지 — 수급(외국인·기관·개인)과 시총 상위 종목 등락을 근거로.",
                 "급등락의 원인을 시황 기사·뉴스를 근거로. 장중에 새로 나온 재료가 있으면 그것부터."),
}


def _commentary(ctx: dict):
    """LLM 해설. 실패하면 None — 호출부가 규칙 요약으로 내려간다."""
    if not llm.available():
        return None
    variant = ctx.get("variant") or ctx["market"]
    s = _SECTIONS[variant]
    g = _SECTION_GUIDE[variant]
    n = ctx.get("nNews") or BRIEF_NEWS_TOTAL
    note = _MARKET_NOTE[variant] + (_AFTER_CLOSE_NOTE if ctx.get("closePrev") else "")
    prompt = (_INSTRUCT.format(s0=s[0], s1=s[1], s2=s[2], s3=s[3], d0=g[0], d1=g[1], n=n,
                               note=note, axes=_AXES[variant], prev_label=_PREV_LABEL[variant])
              + "\n[자료]\n" + context_text(ctx))
    data = llm.brief_analysis(prompt)
    if not data:
        log.warn(f"{variant}: LLM 해설 실패 — 규칙 요약으로 보냅니다")
        return None
    parsed = parse_commentary(data, ctx["candidates"], variant, n_news=n)
    if parsed is None:
        log.warn(f"{variant}: LLM 응답 형식이 맞지 않음 — 규칙 요약으로 보냅니다")
    return parsed


def context_text(ctx: dict) -> str:
    """프롬프트의 [자료] 부분. 테스트가 이 문자열로 무엇이 넘어가는지 확인한다."""
    market = ctx["market"]
    variant = ctx.get("variant") or market
    now = now_utc()
    local = now.astimezone(KST if market == "KR" else ET)
    kst = now.astimezone(KST)
    session = ctx["session"]
    L: list[str] = []
    if variant == "KR-close":
        L.append(f"[작성 시점] {kst:%Y-%m-%d %H:%M} KST · 국장 마감 브리핑 "
                 f"(오늘 {session:%m/%d}({WEEKDAY_KR[session.weekday()]}) 국장은 15:30 에 마감)")
    elif market == "KR":
        L.append(f"[작성 시점] {kst:%Y-%m-%d %H:%M} KST · 국장 개장 전 브리핑 "
                 f"(오늘 {session:%m/%d}({WEEKDAY_KR[session.weekday()]}) 국장은 09:00 개장)")
    else:
        L.append(f"[작성 시점] 미국 동부 {local:%Y-%m-%d %H:%M} (한국 {kst:%m/%d %H:%M}) · "
                 f"미장 개장 전 브리핑 (오늘 {session:%m/%d} 미국장은 09:30 ET 개장)")
    o = ctx.get("outlook")
    if o:
        L.append(f"[오늘 장 전망 점수 — 규칙 계산] {o['score']}점 '{o['label']}' · 근거: {o.get('reason') or '-'}")
    morning = ctx.get("morning")
    if morning and (morning.get("mood") or {}).get("label"):
        m = morning["mood"]
        L.append(f"[오늘 아침 브리핑] 개장 전 전망 {m.get('score')}점 '{m['label']}' · {m.get('reason') or ''}")

    L.append("\n[지표] 종가 기준. 괄호: 최근 5거래일·20거래일 등락, 52주 최고 종가 대비")
    for i in ctx["indices"]:
        if i.get("value") is None:
            continue
        L.append("- " + _index_line(i))
    for key, f in (ctx.get("futures") or {}).items():
        if f.get("live") and f.get("changePct") is not None:
            L.append(f"- {f['name']} {f['value']:,.2f} (실시간) {f['changePct']:+.2f}%")

    flows = ctx.get("flows")
    if flows:
        rows = []
        for name, label in (("KOSPI", "코스피"), ("KOSDAQ", "코스닥")):
            f = flows.get(name)
            if f:
                rows.append(f"{label}({f['date'][5:]}) 외국인 {naver_mod.eok_label(f['foreign'])} · "
                            f"기관 {naver_mod.eok_label(f['institution'])} · "
                            f"개인 {naver_mod.eok_label(f['individual'])}")
        if rows:
            L.append("\n[수급] 순매수(+)/순매도(-), 원")
            L.extend(f"- {r}" for r in rows)

    leaders = ctx.get("leaders") or {}
    for mk, label in (("KR", "국장 시총 상위"), ("US", "미국 대표주")):
        rows = [r for r in leaders.get(mk, []) if r.get("changePct") is not None]
        if rows:
            day = rows[0].get("date") or ""
            L.append(f"\n[{label}] ({day[5:]} 종가)")
            L.append(", ".join(f"{r['name']} {r['changePct']:+.1f}%" for r in rows))

    movers = [m for m in ctx.get("movers") or [] if m.get("changePct") is not None]
    if movers:
        L.append("\n[급등락 종목] (직전 세션)")
        for m in movers:
            note = f" — {m['note']}" if m.get("note") else ""
            L.append(f"- {m['name']} {m['changePct']:+.1f}%{note}")

    wrap = ctx.get("wrap") or []
    if wrap:
        L.append("\n[시황 기사 제목] 최근 순")
        for w in wrap:
            L.append(f"- [{_stamp(w.get('publishedAt'))} {w.get('source', '')}] {w['title']}")

    cands = ctx.get("candidates") or []
    if cands:
        L.append("\n[후보 기사] 번호로 고르세요")
        for i, n in enumerate(cands, 1):
            summary = T.truncate(n.get("summary") or "", 140)
            extra = f" (같은 사건 다른 매체 {len(n['related'])}건)" if n.get("related") else ""
            tick = ", ".join(t["name"] for t in (n.get("tickers") or [])[:2])
            tick = f" #{tick}" if tick else ""
            L.append(f"[{i}] ({n.get('market')} · {n.get('source', '')} · {_stamp(n.get('publishedAt'))}){tick} "
                     f"{n['title']}{extra}" + (f"\n    요약: {summary}" if summary else ""))

    cal = ctx.get("calendar") or []
    if cal:
        L.append("\n[예정된 실적 발표] 오늘")
        L.extend(f"- {c['title']} · {c['time']}" for c in cal)
    upcoming = ctx.get("upcoming") or []
    if upcoming:
        L.append("\n[다가오는 실적 발표] 앞으로 일주일")
        L.extend(f"- {u['date'][5:]} {u['name']}({u['code']}) · {u['when']}" for u in upcoming)

    close_prev = ctx.get("closePrev") or {}
    if close_prev.get("threeLines"):
        L.append(f"\n[어제 장 마감 브리핑] ({close_prev.get('date')}) {close_prev.get('headline') or ''}")
        L.extend(f"- {line}" for line in close_prev["threeLines"])

    prev = ctx.get("prev") or {}
    if prev.get("threeLines"):
        label = _PREV_LABEL.get(variant, "어제 브리핑의 3가지")
        L.append(f"\n[{label}] ({prev.get('date')}) — 새 진전이 없으면 반복 금지")
        L.extend(f"- {line}" for line in prev["threeLines"])
    return "\n".join(L)


def _index_line(i: dict) -> str:
    unit = i.get("unit")
    v = i["value"]
    if unit == "%":
        value = f"{v:.2f}%"
        chg = f"{i['change'] * 100:+.0f}bp" if i.get("change") is not None else ""
    else:
        value = f"{v:,.2f}" + ("원" if unit == "원" else "")
        chg = f"{i['changePct']:+.2f}%" if i.get("changePct") is not None else ""
    trend = [f"{label} {i[k]:+.1f}%" for k, label in
             (("change5d", "5일"), ("change20d", "20일"), ("fromHigh52w", "고점 대비"))
             if i.get(k) is not None]
    extra = f" ({', '.join(trend)})" if trend else ""
    gap = i.get("overnightGap")
    gap_txt = f" · 코스피 마감 뒤 미국장에서 {gap:+.1f}% 더 움직임" if gap is not None else ""
    day = (i.get("date") or "")[5:]
    return f"{i['name']} {value} ({day}) {chg}{extra}{gap_txt}"


def _stamp(value: str | None) -> str:
    dt = parse_iso(value)
    return dt.astimezone(KST).strftime("%m/%d %H:%M") if dt else "?"


def parse_commentary(data: dict, cands: list[dict], market: str, *,
                     n_news: int = BRIEF_NEWS_TOTAL):
    """LLM 응답을 검증해 (headline, threeLines, analysis, picks) 로. 못 쓰면 None.

    모델이 지시를 어겨도 브리핑에 그대로 새지 않게 여기서 거른다 — 차트 신호 줄,
    없는 후보 번호, 중복 번호, 비어 있는 해설 단락.
    """
    def text(v, limit: int) -> str:
        return T.truncate(" ".join(str(v or "").split()), limit)

    three = [text(x, 220) for x in (data.get("threeLines") or []) if isinstance(x, str)]
    three = [x for x in three if x and "차트 지표" not in x and "매수 우위" not in x][:3]
    if len(three) < 2:
        return None

    analysis = []
    titles = _SECTIONS[market]
    for sec in data.get("analysis") or []:
        if not isinstance(sec, dict):
            continue
        body = text(sec.get("body"), 900)
        if body:
            analysis.append({"title": text(sec.get("title"), 20) or titles[len(analysis) % 4],
                             "body": body})
    analysis = analysis[:4] or None

    picks, used = [], set()
    for row in data.get("news") or []:
        if not isinstance(row, dict):
            continue
        try:
            idx = int(row.get("id")) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= idx < len(cands) or idx in used:
            continue
        used.add(idx)
        n = cands[idx]
        ko = text(row.get("titleKo"), 120) if not _has_hangul(n.get("title", "")) else ""
        picks.append((n, text(row.get("why"), 160) or None, ko or None))
        if len(picks) >= n_news:
            break
    if len(picks) < n_news:       # 모델이 덜 골랐으면 규칙 순서로 채운다
        rest = [n for i, n in enumerate(cands) if i not in used]
        for n in _pick_news(rest, key="briefScore")[:n_news - len(picks)]:
            picks.append((n, None, None))

    headline = text(data.get("headline"), 80) or three[0]
    return headline, three, analysis, picks


def _has_hangul(s: str) -> bool:
    return any("가" <= ch <= "힣" for ch in s)


# --------------------------------------------------------------------------
# 규칙 요약 (LLM 없을 때)
# --------------------------------------------------------------------------
def _rule_summary(ctx: dict) -> tuple[str, list[str]]:
    market = ctx["market"]
    label = "국장" if market == "KR" else "미장"
    o = ctx["outlook"]
    headline = f"{label} 개장 전 점검 · 오늘 장 전망 {o['label']}"
    find = {i["key"]: i for i in ctx["indices"]}
    lines: list[str] = []

    home = find.get("KS11" if market == "KR" else "US500")
    if home and home.get("changePct") is not None:
        move = "올라" if home["changePct"] >= 0 else "내려"
        line = (f"직전 거래일 {home['name']}는 {abs(home['changePct']):.2f}% {move} "
                f"{home['value']:,.2f}에 마감했습니다.")
        f = (ctx.get("flows") or {}).get("KOSPI")
        if market == "KR" and f and f.get("foreign"):
            side = "순매수" if f["foreign"] > 0 else "순매도"
            line += f" 외국인은 {naver_mod.eok_label(abs(f['foreign'])).lstrip('+')}원어치를 {side}했습니다."
        lines.append(line)

    if o.get("drivers"):
        lines.append(f"개장 전 신호는 '{o['label']}' 쪽입니다 — {', '.join(o['drivers'])}.")

    wrap = ctx.get("wrap") or []
    cands = ctx.get("candidates") or []
    top = wrap[0]["title"] if wrap else cands[0]["title"] if cands else None
    if top:
        lines.append(f"주목할 소식: {T.truncate(top, 70)}")
    for n in cands[1:]:
        if len(lines) >= 3:
            break
        if n["title"] != top:
            lines.append(f"주목할 소식: {T.truncate(n['title'], 70)}")
    return headline, lines[:3]


# --------------------------------------------------------------------------
# 뉴스·일정·차트 블록
# --------------------------------------------------------------------------
def _pick_news(news: list[dict], *, key: str = "importance",
               total: int = BRIEF_NEWS_TOTAL) -> list[dict]:
    """Top stories for the brief, with a floor reserved for single-stock news.

    Straight importance ranking lets macro stories (Fed, FX, tariffs) take every
    slot — they score high on outlet weight and market-moving keywords by
    construction. Reserving `BRIEF_NEWS_TICKER_MIN` seats for items tagged to a
    ticker keeps "why did my stock move" in the brief without demoting macro
    below its own rank; the remaining seats stay pure importance order.

    같은 종목이 주인공인 기사는 한 자리만 준다 — 2026-10-15 국장 브리핑은 6자리 중
    3자리가 신한지주였다.

    `news` must already be sorted by `key`, descending.
    """
    def lead(n):
        tickers = n.get("tickers") or []
        return tickers[0].get("code") if tickers else None

    picks: list[dict] = []
    chosen: set[int] = set()
    leads: set[str] = set()

    def take(n) -> bool:
        code = lead(n)
        if id(n) in chosen or (code and code in leads):
            return False
        picks.append(n)
        chosen.add(id(n))
        if code:
            leads.add(code)
        return True

    for n in news:
        if sum(1 for p in picks if p.get("tickers")) >= BRIEF_NEWS_TICKER_MIN:
            break
        if n.get("tickers"):
            take(n)
    for n in news:
        if len(picks) >= total:
            break
        take(n)

    picks.sort(key=lambda n: n.get(key, 0), reverse=True)
    return picks[:total]


def _home_first(cands: list[dict]) -> list[dict]:
    """LLM 없이 고를 때는 국내·글로벌 기사를 먼저 — 미국 기사는 자리가 남을 때만, 순서도 뒤.

    후보 점수만으로 고르면 번역도 해설도 없는 영문 기사(블룸버그 테슬라 인터뷰)가 국장
    브리핑 맨 위에 올라왔다. LLM 은 한국 시장에 의미 있는 미국 기사만 고르지만 규칙은 못 한다.
    고를 때와 늘어놓을 때 두 번 쓴다 — 고른 뒤 점수순 정렬이 미국 기사를 다시 맨 위로 올린다.
    """
    return ([n for n in cands if n.get("market") != "US"]
            + [n for n in cands if n.get("market") == "US"])


def _top_news(n: dict, *, why: str | None = None, title_ko: str | None = None) -> dict:
    return {
        "title": n["title"],
        "titleKo": title_ko or n.get("titleKo"),
        "url": n["url"],
        "source": n.get("source"),
        # 그 기사만의 한 줄 해설 (LLM). 없으면 비워 둔다 — 예전 키워드 규칙 문구
        # ("금리가 오르면 …")는 엉뚱한 기사에 붙어서 없는 것보다 나빴다.
        "why": why,
        "tickers": [{"code": t["code"], "name": t["name"]}
                    for t in n.get("tickers", [])[:3]],
        "importance": n.get("importance"),
    }


def _upcoming(market: str, session_date) -> list[dict]:
    """해설의 "앞으로 볼 것"에 넘길 다음 일주일 실적 일정 (오늘 것은 `calendar` 에 있다).

    오늘 일정만 주면 연결 종목 발표가 없는 날 모델이 "AI 기업 실적에 주목" 같은 막연한
    문장밖에 못 쓴다 (2026-10-15 리허설에서 그랬다). 국장은 한국 연결 종목, 미장은
    시가총액 상위만 넘긴다. 실패해도 해설은 나간다.
    """
    if not CALENDAR_EARNINGS:
        return []
    try:
        items = calendar_mod.fetch_earnings(session_date + timedelta(days=1), days=7)
    except Exception as exc:
        log.warn(f"upcoming earnings skipped: {exc}")
        return []
    if market == "KR":
        items = [i for i in items if i["code"] in KR_LINKED_US]
    else:
        items = [i for i in items if (i["marcap"] or 0) >= 100_000_000_000]
    return [{"date": i["date"], "code": i["code"], "name": i["name"], "when": i["when"]}
            for i in items[:8]]


def _calendar(market: str, session_date, tickers: list[dict] | None = None) -> list[dict]:
    """오늘 예정된 재료 — 지금으로선 미국 실적 발표.

    브리핑에서 유일하게 **선행하는** 항목이다. 나머지는 전부 이미 일어난 일을
    설명한다. 급등을 맞힐 수는 없어도 "오늘 밤 이 종목이 실적을 낸다"는 미리
    말해 줄 수 있고, 그게 대비의 최소 단위다.

    국장 브리핑(07:45~08:40 KST)에는 **그날 밤 열리는 미국장** 일정을 싣는다.
    한국 아침 기준으로 아직 안 일어난 일이라 진짜 예고가 된다. 미장 브리핑은
    개장 직전이라 같은 날짜를 그대로 쓴다. 국장 브리핑은 한국 증시와 이어진
    종목(`KR_LINKED_US`)만 싣는다.
    """
    if not CALENDAR_EARNINGS:
        return []
    try:
        items = calendar_mod.fetch_earnings(session_date)
    except Exception as exc:      # 캘린더가 죽어도 브리핑은 나가야 한다
        log.warn(f"calendar skipped: {exc}")
        return []

    if market == "KR":
        items = [i for i in items if i["code"] in KR_LINKED_US]
    same_day = [i for i in items if i["date"] == session_date.isoformat()]
    picked = (same_day or items)[:CALENDAR_MAX_ITEMS]
    return [{
        "time": i["when"],
        "title": f"{short_name(i['name'])} ({i['code']}) 실적 발표",
        "code": i["code"],
        "market": i["market"],
        "epsForecast": i["epsForecast"],
        "importance": "high" if (i["marcap"] or 0) >= 100_000_000_000 else "normal",
    } for i in picked]


_NAME_TAIL = re.compile(
    r"(,?\s+(Inc\.?|Incorporated|Corporation|Corp\.?|Company|Co\.|Ltd\.?|Limited|plc|"
    r"Holdings?|Group|N\.V\.|S\.A\.|AG|SE))+\s*$", re.IGNORECASE)


def short_name(name: str) -> str:
    """"Taiwan Semiconductor Manufacturing Company Ltd." → "Taiwan Semiconductor Manufacturing".

    실적 캘린더 이름은 등기명이라 텔레그램 한 줄을 넘긴다. 앞의 "The " 와 법인 꼬리표만 뗀다.
    """
    s = re.sub(r"^The\s+", "", (name or "").strip())
    return _NAME_TAIL.sub("", s).strip() or name


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
