"""브리핑 품질 회귀 — 2026-10-15 사용자 신고 여섯 가지 (99-스펙변경이력).

1. "오늘 꼭 알아야 할 3가지"가 매일 같다 — 3줄 중 2줄이 틀(간밤 지수·차트 신호 수)이었다.
2. 주요 뉴스 품질 — 같은 사건 3건, 무관한 기사, 엉뚱한 키워드 💡.
3. 코스피 -7.6% 급락의 이유가 없다.
4. 그날 아침 분위기가 "중립 47점"이었다.
5. 쓸데없는 내용이 많다.
6. 왜 움직였고 앞으로 어떨지 해설이 필요하다.

네트워크는 타지 않는다. 숫자는 실제 2026-10-14~15 값을 쓴다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from pipeline.analyze import curate, llm, mood
from pipeline.build import brief
from pipeline.build import site_data
from pipeline.collect import naver
from pipeline.collect.macro import korea_overnight_gap, trend
from pipeline.config import BRIEF_NEWS_TOTAL
from pipeline.notify import telegram


def idx(key, pct, value=100.0, date="2026-10-14", **extra):
    return {"key": key, "name": key, "value": value, "changePct": pct, "date": date,
            "unit": "pt", **extra}


# 2026-10-15 국장 브리핑 시점(07:50 KST)에 알 수 있던 값들.
OCT15_MORNING = [
    idx("KS11", -0.44, 6008.81), idx("USD/KRW", 0.11, 1341.77, unit="원"),
    idx("US500", -1.11), idx("IXIC", -1.88), idx("^SOX", -4.30),
    idx("VIX", 10.48, 16.87), idx("EWY", -4.04, 159.83, overnightGap=-1.72),
]


# --------------------------------------------------------------------------
# 4. 오늘 장 전망
# --------------------------------------------------------------------------

def test_outlook_flags_the_oct15_crash_morning():
    """그날 아침 브리핑은 "중립 47점"이었다. 밤사이 반도체·한국 ETF 급락을 봤어야 했다."""
    o = mood.outlook("KR", OCT15_MORNING)
    assert o["score"] < 35 and o["label"] == "약세 우려" and o["color"] == "red"
    assert o["kind"] == "outlook"
    assert "필라델피아 반도체" in o["reason"]


def test_outlook_is_neutral_on_a_quiet_night():
    quiet = [idx("KS11", 0.1), idx("USD/KRW", 0.0), idx("IXIC", 0.1), idx("^SOX", -0.1),
             idx("VIX", 0.0, 16.0), idx("EWY", 0.2, overnightGap=0.1)]
    o = mood.outlook("KR", quiet)
    assert 45 <= o["score"] <= 60
    assert o["color"] in ("amber", "green")


def test_outlook_survives_missing_and_nan_inputs():
    """소스가 비거나 NaN 을 줘도 터지지 않고, NaN 을 강세로 읽지도 않는다."""
    assert mood.outlook("KR", [])["score"] == 50
    o = mood.outlook("KR", [idx("^SOX", -4.3), idx("EWY", float("nan"), overnightGap=float("nan"))])
    assert o["score"] < 35


def test_us_outlook_uses_live_futures_only():
    base = [idx("US500", 0.0), idx("VIX", 0.0, 18.0)]
    down = mood.outlook("US", base, futures={"ES=F": {"changePct": -1.5, "live": True}})
    stale = mood.outlook("US", base, futures={"ES=F": {"changePct": -1.5, "live": False}})
    assert down["score"] < stale["score"]
    assert "S&P 500 선물" in down["reason"]


def _frames(kospi, ewy, fx=None, start="2026-09-01"):
    days = pd.bdate_range(start, periods=len(kospi))
    k = pd.DataFrame({"Close": kospi}, index=days)
    e = pd.DataFrame({"Close": ewy}, index=days[:len(ewy)])
    f = pd.DataFrame({"Close": fx or [1350.0] * len(kospi)}, index=days)
    return e, k, f


def test_overnight_gap_ignores_moves_kospi_already_made():
    """코스피가 -7% 빠진 날 밤 EWY 도 -7% 따라가면 '새 하락'이 아니다 (gap ≈ 0)."""
    kospi = [6000.0] * 25 + [5580.0]
    ewy = [160.0] * 25 + [148.8]
    e, k, f = _frames(kospi, ewy)
    assert abs(korea_overnight_gap(e, k, f)) < 0.3


def test_overnight_gap_measures_the_move_after_kospi_closed():
    kospi = [6000.0] * 26
    ewy = [160.0] * 25 + [164.8]                # 코스피는 그대로, 미국장에서 EWY +3%
    e, k, f = _frames(kospi, ewy)
    assert korea_overnight_gap(e, k, f) == pytest.approx(3.0, abs=0.1)


def test_overnight_gap_is_none_when_ewy_is_stale():
    """미국 휴장이면 EWY 마지막 봉이 코스피보다 오래됐다 — 새 정보가 없다."""
    kospi = [6000.0] * 26
    ewy = [160.0] * 25
    e, k, f = _frames(kospi, ewy)
    assert korea_overnight_gap(e, k, f) is None


def test_trend_reports_multi_day_context():
    df = pd.DataFrame({"Close": [100.0] * 20 + [90.0, 85.0, 80.0, 78.0, 76.0, 75.0]})
    t = trend(df)
    assert t["change5d"] == pytest.approx(-16.67, abs=0.01)
    assert t["fromHigh52w"] == pytest.approx(-25.0)


# --------------------------------------------------------------------------
# 분위기 점수 — 상승·하락 종목 수
# --------------------------------------------------------------------------

def test_mood_breadth_uses_real_counts():
    """예전에는 상위 8·하위 8 목록 길이를 세서 매일 '8개 상승·8개 하락'이었다."""
    bad = mood.score_market("KR", [], {"up": [{}] * 8, "down": [{}] * 8})
    assert "8개 상승" not in bad["reason"]
    good = mood.score_market("KR", [], {"up": 40, "down": 270})
    assert good["score"] < 20 and "40개 상승·270개 하락" in good["reason"]


def test_overview_breadth_counts_latest_day_stocks_only():
    items = [
        {"market": "KR", "exchange": "KOSPI", "changePct": -3.0, "date": "2026-10-15"},
        {"market": "KR", "exchange": "KOSPI", "changePct": 1.0, "date": "2026-10-15"},
        {"market": "KR", "exchange": "KOSPI", "changePct": 0.0, "date": "2026-10-15"},
        {"market": "KR", "exchange": "ETF", "changePct": -5.0, "date": "2026-10-15"},
        {"market": "KR", "exchange": "KOSDAQ", "changePct": 9.0, "date": "2026-10-10"},
        {"market": "US", "exchange": "NYSE", "changePct": 2.0, "date": "2026-10-14"},
    ]
    b = site_data._breadth(items, "KR")
    assert (b["up"], b["down"], b["flat"], b["date"]) == (1, 1, 1, "2026-10-15")


# --------------------------------------------------------------------------
# 2. 뉴스 후보
# --------------------------------------------------------------------------

NOW = datetime(2026, 10, 15, 22, 40, tzinfo=timezone.utc)


def news(title, importance=60, market="KR", tickers=None, hours_ago=3, url=None, summary=""):
    return {"title": title, "summary": summary, "importance": importance, "market": market,
            "url": url or f"https://x/{abs(hash(title))}",
            "source": "연합뉴스", "tickers": [{"code": c, "name": c} for c in (tickers or [])],
            "publishedAt": (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")}


def test_candidates_drop_junk_irrelevant_and_already_sent():
    sent = news("어제 실린 기사 코스피 전망", 90, url="https://x/sent")
    items = [
        news("[게시판] 소비자원, '한국 ESG 혁신정책 대상' 최우수상", 66),
        news("광주은행, 어르신 치매·실종예방 캠페인…4년간 20억 지원", 64),
        news("편의점 김밥 한 줄론 배 안찼는데 나트륨 함량", 56),
        sent,
        news("코스피·코스닥 동시 서킷브레이커…올해 5번째", 48),
        news("외국인 3조 매도에 반도체 급락", 55),
    ]
    got = curate.candidates(items, "KR", since=NOW - timedelta(hours=30),
                            exclude_urls={"https://x/sent"})
    titles = [n["title"] for n in got]
    assert titles[0].startswith("코스피·코스닥 동시 서킷브레이커"), "지수 전체 사건이 맨 위로"
    assert not any("게시판" in t or "치매" in t or "김밥" in t for t in titles)
    assert "어제 실린 기사 코스피 전망" not in titles


def test_candidates_merge_same_story_and_cap_per_ticker():
    items = [
        news("[속보] 공포의 '검은 목요일'…코스피·코스닥 7%대 급락 마감", 56),
        news("[속보] 공포의 ‘검은 목요일’…코스피·코스닥 7%대 급락 마감(종합)", 55),
        news("'롯데손보 인수' 신한지주, 4.7% 하락(종합)", 67, tickers=["055550"]),
        news("롯데손보 품는 신한금융에 축하보다 우려", 67, tickers=["055550"]),
        news("'승자의 저주' 걱정에…롯데손보 삼킨 신한지주 급락", 66, tickers=["055550"]),
    ]
    got = curate.candidates(items, "KR", since=NOW - timedelta(hours=30))
    crash = [n for n in got if "검은 목요일" in n["title"]]
    assert len(crash) == 1 and len(crash[0]["related"]) == 1
    assert sum(1 for n in got if n["tickers"] and n["tickers"][0]["code"] == "055550") <= 2


def test_kr_candidates_include_us_stock_stories_but_us_brief_has_no_kr():
    items = [news("Dell stock plunges 11% as AI fears mount", 74, market="US", tickers=["DELL"]),
             news("Bank of America fined $1.2 billion", 74, market="US"),
             news("삼성전자 9% 급락", 70, tickers=["005930"])]
    kr = [n["title"] for n in curate.candidates(items, "KR", since=NOW - timedelta(hours=30))]
    assert "Dell stock plunges 11% as AI fears mount" in kr
    assert "Bank of America fined $1.2 billion" not in kr, "종목 태그도 지수 사건도 아닌 미국 기사"
    us = [n["title"] for n in curate.candidates(items, "US", since=NOW - timedelta(hours=30))]
    assert "삼성전자 9% 급락" not in us


def test_old_news_is_outside_the_window():
    items = [news("코스피 급락 마감", 80, hours_ago=50)]
    assert curate.candidates(items, "KR", since=NOW - timedelta(hours=30)) == []


# --------------------------------------------------------------------------
# 1·6. LLM 응답 검증
# --------------------------------------------------------------------------

def _cands(n=8):
    out = [dict(news(f"후보 기사 {i} 코스피", 70 - i), briefScore=70 - i, related=[])
           for i in range(n)]
    if n > 3:
        out[3]["title"] = "Dell stock plunges 11% as AI fears mount"
    return out


def test_commentary_drops_chart_lines_and_bad_ids():
    data = {
        "headline": "코스피 급락",
        "threeLines": ["어제 코스피는 외국인 매도로 7.6% 급락했습니다.",
                       "차트 지표 기준으로 매수 우위 종목이 69개입니다.",
                       "간밤 반도체 지수가 4.3% 내려 오늘도 부담입니다.",
                       "오늘 밤 TSMC 실적이 반도체 심리를 가를 수 있습니다."],
        "analysis": [{"title": "어제 국장", "body": "외국인이 3.8조를 팔았습니다."},
                     {"title": "간밤 미국", "body": ""}],
        "news": [{"id": 2, "why": "a"}, {"id": 2, "why": "dup"}, {"id": 99, "why": "x"},
                 {"id": "4", "why": "델 급락은 AI 서버 수요 우려", "titleKo": "델 주가 11% 급락"},
                 {"id": 1, "why": "b", "titleKo": "무시돼야 함"}],
    }
    headline, three, analysis, picks = brief.parse_commentary(data, _cands(), "KR")
    assert len(three) == 3 and not any("차트 지표" in x for x in three)
    assert [a["title"] for a in analysis] == ["어제 국장"], "빈 단락은 버린다"
    assert len(picks) == BRIEF_NEWS_TOTAL, "모델이 덜 고르면 규칙 순서로 채운다"
    titles = [n["title"] for n, _, _ in picks]
    assert len(set(titles)) == len(titles)
    dell = next(p for p in picks if p[0]["title"].startswith("Dell"))
    assert dell[2] == "델 주가 11% 급락"
    first = next(p for p in picks if p[0]["title"] == "후보 기사 0 코스피")
    assert first[2] is None, "한글 기사에는 번역 제목을 붙이지 않는다"


def test_commentary_rejects_unusable_answers():
    assert brief.parse_commentary({"threeLines": ["하나뿐"]}, _cands(), "KR") is None
    assert brief.parse_commentary({}, _cands(), "KR") is None


def test_rule_summary_has_no_chart_count_or_boilerplate():
    ctx = {"market": "KR", "indices": [idx("KS11", -7.57, 5554.22)],
           "outlook": mood.outlook("KR", OCT15_MORNING),
           "flows": {"KOSPI": {"date": "2026-10-15", "foreign": -37637,
                               "institution": 17176, "individual": 13967}},
           "wrap": [{"title": "[1015마감체크] 코스피·코스닥 7%대 급락… AI 투자 수익성 우려에 美 물가 쇼크까지"}],
           "candidates": _cands(3)}
    headline, lines = brief._rule_summary(ctx)
    assert len(lines) == 3
    joined = " ".join(lines)
    assert "차트" not in joined and "매수 우위" not in joined
    assert "7.57%" in lines[0] and "외국인은 3조 7,637억원어치를 순매도" in lines[0], \
        "순매도 금액 앞에 '+' 가 붙으면 안 된다"
    assert "약세 우려" in headline


def test_context_carries_flows_wrap_and_yesterdays_points():
    ctx = {"market": "KR", "session": datetime(2026, 10, 16).date(),
           "outlook": mood.outlook("KR", OCT15_MORNING), "indices": OCT15_MORNING,
           "futures": {}, "flows": {"KOSPI": {"date": "2026-10-15", "foreign": -37637,
                                              "institution": 17176, "individual": 13967}},
           "leaders": {"KR": [{"name": "삼성전자", "changePct": -11.51, "date": "2026-10-15"}],
                       "US": []},
           "movers": [], "wrap": [{"title": "코스피 7일째 추락", "source": "뉴스1",
                                  "publishedAt": "2026-10-15T08:48:00Z"}],
           "candidates": _cands(2), "calendar": [],
           "upcoming": [{"date": "2026-10-21", "code": "TSLA", "name": "Tesla, Inc.",
                         "when": "장 마감 후"}],
           "prev": {"date": "2026-10-15", "threeLines": ["어제 말한 것"]}}
    text = brief.context_text(ctx)
    assert "10-21 Tesla, Inc.(TSLA) · 장 마감 후" in text, "'앞으로 볼 것'이 구체적인 일정을 쓸 재료"
    assert "외국인 -3조 7,637억" in text
    assert "코스피 7일째 추락" in text
    assert "어제 말한 것" in text and "반복 금지" in text
    assert "삼성전자 -11.5%" in text
    assert "코스피 마감 뒤 미국장에서 -1.7% 더 움직임" in text


# --------------------------------------------------------------------------
# 직전 브리핑 · 뉴스 창
# --------------------------------------------------------------------------

def test_previous_brief_skips_same_session(tmp_path):
    (tmp_path / "brief").mkdir()
    for day in ("2026-10-14", "2026-10-15", "2026-10-16"):
        (tmp_path / "brief" / f"{day}-KR.json").write_text(f'{{"date": "{day}"}}', encoding="utf-8")
    prev = brief.previous_brief("KR", datetime(2026, 10, 16).date(), data_dir=tmp_path)
    assert prev["date"] == "2026-10-15"


def test_news_window_starts_before_previous_brief():
    prev = {"generatedAt": "2026-10-14T22:50:08Z"}
    since = brief.news_since(prev, now=NOW)
    assert since == datetime(2026, 10, 14, 20, 50, 8, tzinfo=timezone.utc)
    assert brief.news_since(None, now=NOW) == NOW - timedelta(hours=30)


# --------------------------------------------------------------------------
# 수급
# --------------------------------------------------------------------------

def test_flows_parse_and_label():
    row = naver.parse_flows({"bizdate": "20261015", "personalValue": "+13,967",
                       "foreignValue": "-37,637", "institutionalValue": "+17,176"})
    assert row == {"date": "2026-10-15", "individual": 13967, "foreign": -37637,
                   "institution": 17176}
    assert naver.eok_label(-37637) == "-3조 7,637억"
    assert naver.eok_label(2228) == "+2,228억"
    assert naver.eok_label(20000) == "+2조"
    assert naver.parse_flows({"bizdate": "x"}) is None


# --------------------------------------------------------------------------
# 5. 텔레그램 메시지
# --------------------------------------------------------------------------

def _brief(**over):
    b = {"market": "KR", "date": "2026-10-16", "late": False,
         "headline": "코스피 급락 뒤 첫 거래일",
         "threeLines": ["하나", "둘", "셋"],
         "mood": {"score": 18, "label": "약세 우려", "color": "red", "kind": "outlook",
                  "reason": "필라델피아 반도체 -4.3%"},
         "analysis": [{"title": "어제 국장", "body": "외국인이 3.8조를 팔았습니다."},
                      {"title": "흐름 읽기", "body": "물가 → 금리 → 성장주."}],
         "marketSnapshot": [{"key": "^TNX", "name": "미 10년물 금리", "value": 5.19,
                             "change": -0.027, "changePct": -0.52, "unit": "%"},
                            {"key": "KS11", "name": "코스피", "value": 5554.22,
                             "change": -454.59, "changePct": -7.57, "unit": "pt"}],
         "flows": {"KOSPI": {"date": "2026-10-15", "foreign": -37637,
                             "institution": 17176, "individual": 13967}},
         "topNews": [{"title": "Dell plunges", "titleKo": "델 11% 급락", "url": "https://d",
                      "source": "CNBC", "why": "AI 서버 수요 우려", "tickers": []},
                     {"title": "기사 둘", "url": "https://e", "source": "연합뉴스",
                      "why": None, "tickers": []}],
         "wrapHeadlines": [{"title": "시황 제목", "url": "https://w", "source": "뉴스1"}],
         "chartSignals": {"counts": {"bullish": 38, "neutral": 141, "bearish": 143},
                          "bullish": [{"name": "동서"}], "bearish": [{"name": "삼성중공업"}]},
         "watchlistMoves": [{"name": "에스원", "changePct": 11.85, "note": "+11.8% 급등"}],
         "calendar": [{"title": "TSMC (TSM) 실적 발표", "time": "개장 전", "importance": "high"}],
         "disclaimer": "투자 권유가 아닙니다.", "siteUrl": "https://s"}
    b.update(over)
    return b


def test_render_leads_with_outlook_and_analysis():
    msg = telegram.render(_brief())
    assert "오늘 장 전망: <b>약세 우려</b> (18점)" in msg
    assert msg.index("오늘 장 전망") < msg.index("오늘 꼭 알아야 할 3가지") < msg.index("시장 해설")
    assert "▸ 어제 국장" in msg and "▸ 흐름 읽기" in msg
    assert "수급(코스피 10-15): 외국인 -3조 7,637억" in msg
    assert "-3bp" in msg, "금리는 bp 로 — '-0.52%' 는 0.52%p 로 오해된다"
    assert "델 11% 급락" in msg and "💡 AI 서버 수요 우려" in msg
    assert msg.count("💡") == 1, "해설 없는 기사에 기본 문구를 붙이지 않는다"
    assert "오늘 밤 미국 실적" in msg
    assert "에스원" not in msg, "관심 종목 블록은 텔레그램에서 뺐다"
    assert "시황 기사" not in msg, "해설이 있으면 시황 제목은 중복이다"
    assert len(telegram._split(msg)) == 1


def test_render_falls_back_to_wrap_headlines_without_analysis():
    msg = telegram.render(_brief(analysis=None))
    assert "🧭 시황 기사" in msg and "시황 제목" in msg


def test_render_keeps_old_mood_wording_for_old_files():
    msg = telegram.render(_brief(mood={"score": 47, "label": "중립", "color": "amber"}))
    assert "오늘 시장 분위기: <b>중립</b>" in msg


# --------------------------------------------------------------------------
# LLM 쿼터 분리
# --------------------------------------------------------------------------

class _Resp:
    def __init__(self, status, payload=None):
        self.status_code, self._payload, self.text = status, payload or {}, "x"

    def json(self):
        return self._payload


def _uses(url: str, model: str) -> bool:
    return f"/models/{model}:" in url        # "3.5-flash" 는 "3.5-flash-lite" 의 앞부분이다


def _llm_env(monkeypatch, post):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setattr(llm, "GEMINI_DELAY_SEC", 0)
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)
    monkeypatch.setattr(llm.requests, "post", post)
    llm.reset()


_OK = {"candidates": [{"content": {"parts": [{"text": '{"threeLines": ["a", "b"]}'}]}}]}


def test_dead_bulk_chain_does_not_disable_the_brief_chain(monkeypatch):
    """대량 체인이 전부 404 여도 브리핑 체인은 살아 있어야 하고, 빌려 쓰지도 않는다."""
    seen = []

    def post(url, **kw):
        seen.append(url)
        bulk = any(_uses(url, m) for m in llm.GEMINI_BULK_MODELS)
        return _Resp(404) if bulk else _Resp(200, _OK)

    _llm_env(monkeypatch, post)
    assert llm.explain_events([{"id": "e", "name": "n", "code": "c", "market": "KR",
                                "date": "2026-10-15", "changePct": -7.0}]) == {}
    assert not any(_uses(u, m) for u in seen for m in llm.GEMINI_BRIEF_MODELS), \
        "대량 작업이 브리핑 모델 쿼터를 쓰면 안 된다"
    assert not llm.available(llm.GEMINI_BULK_MODELS)
    assert llm.available(llm.GEMINI_BRIEF_MODELS)
    assert llm.brief_analysis("p") == {"threeLines": ["a", "b"]}
    llm.reset()


def test_retired_model_falls_through_to_the_next_in_chain(monkeypatch):
    """2026-10-15 밤 실제 사고: 2.5-flash-lite 가 404 'no longer available to new users'."""
    first, second = llm.GEMINI_BULK_MODELS[:2]

    def post(url, **kw):
        return _Resp(404) if _uses(url, first) else _Resp(200, _OK)

    _llm_env(monkeypatch, post)
    assert llm._post("p", models=llm.GEMINI_BULK_MODELS) == {"threeLines": ["a", "b"]}
    assert not llm.available(first) and llm.available(second)
    llm.reset()


def test_daily_quota_moves_the_brief_to_its_backup_model(monkeypatch):
    primary, backup = llm.GEMINI_BRIEF_MODELS[:2]
    daily = {"error": {"details": [{"violations": [
        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier", "quotaValue": "20"}]}]}}
    calls = []

    def post(url, **kw):
        calls.append(url)
        return _Resp(429, daily) if _uses(url, primary) else _Resp(200, _OK)

    _llm_env(monkeypatch, post)
    assert llm.brief_analysis("p") == {"threeLines": ["a", "b"]}
    assert sum(_uses(u, primary) for u in calls) == 1, "일일 한도면 같은 모델을 재시도하지 않는다"
    assert any(_uses(u, backup) for u in calls)
    llm.reset()


def test_unsupported_thinking_config_is_retried_without_it(monkeypatch):
    """`gemini-3.5-flash-lite` 는 `thinkingBudget: 0` 을 400 으로 거절했다."""
    bodies = []

    def post(url, json=None, **kw):
        bodies.append(json["generationConfig"].copy())
        return _Resp(400) if "thinkingConfig" in json["generationConfig"] else _Resp(200, _OK)

    _llm_env(monkeypatch, post)
    assert llm._post("p", models=["gemini-x"]) == {"threeLines": ["a", "b"]}
    assert "thinkingConfig" in bodies[0] and "thinkingConfig" not in bodies[-1]
    assert llm.available("gemini-x")
    llm.reset()


def test_thinking_config_matches_model_generation():
    assert llm._thinking("gemini-2.5-flash", 0) == {"thinkingBudget": 0}
    assert llm._thinking("gemini-3.5-flash-lite", 0) == {"thinkingLevel": "minimal"}
    assert llm._thinking("gemini-3.5-flash", 2048) == {"thinkingLevel": "medium"}
