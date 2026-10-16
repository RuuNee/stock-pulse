"""국장 마감 브리핑 — 코스피가 ±2% 넘게 움직인 날에만 (2026-10-16 사용자 결정).

장전 브리핑만으로는 2026-10-15 같은 장중 급락(-7.6%)의 이유가 다음 날 아침에야
나왔다. 매일 보내면 하루 세 통이라 소음이 되므로 큰 변동일만 보낸다. 네트워크는
타지 않는다.
"""

from __future__ import annotations

import json
from datetime import date, datetime

import pytest

from pipeline import gate
from pipeline.build import brief
from pipeline.collect import naver
from pipeline.config import CLOSE_BRIEF_MIN_MOVE, KST
from pipeline.notify import telegram


def kst(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=KST)


@pytest.fixture()
def data_dir(tmp_path):
    (tmp_path / "brief").mkdir()
    return tmp_path


# --------------------------------------------------------------------------
# 게이트
# --------------------------------------------------------------------------

def mode(now, data_dir, move):
    return gate.close_mode("KR", now=now, data_dir=data_dir, index_move=lambda: move)[0]


def test_big_move_after_close_sends(data_dir):
    assert mode(kst(2026, 10, 15, 16, 5), data_dir, -7.57) == gate.ON_TIME
    assert mode(kst(2026, 10, 15, 16, 5), data_dir, +2.4) == gate.ON_TIME


def test_small_move_is_skipped(data_dir):
    """매일 보내면 소음이다 — ±2% 미만은 다음 날 아침 브리핑으로 충분하다."""
    assert mode(kst(2026, 10, 16, 16, 5), data_dir, 1.61) == gate.SKIP
    assert mode(kst(2026, 10, 16, 16, 5), data_dir, -(CLOSE_BRIEF_MIN_MOVE - 0.01)) == gate.SKIP


def test_unknown_or_unclosed_move_is_skipped(data_dir):
    """마감값을 모르면 보내지 않는다 — 헛경보가 침묵보다 나쁘고, 다음 슬롯이 다시 본다."""
    assert mode(kst(2026, 10, 15, 16, 5), data_dir, None) == gate.SKIP


@pytest.mark.parametrize("hour,minute", [(15, 20), (15, 39), (20, 31), (23, 0)])
def test_outside_window_is_skipped(data_dir, hour, minute):
    assert mode(kst(2026, 10, 15, hour, minute), data_dir, -7.57) == gate.SKIP


def test_holiday_and_duplicate_are_skipped(data_dir):
    assert mode(kst(2026, 10, 9, 16, 0), data_dir, -5.0) == gate.SKIP     # 한글날
    (data_dir / "brief" / "2026-10-15-KR-close.json").write_text("{}", encoding="utf-8")
    assert mode(kst(2026, 10, 15, 17, 0), data_dir, -7.57) == gate.SKIP


def test_morning_brief_file_does_not_block_the_close_brief(data_dir):
    """같은 날 장전 브리핑 파일(2026-10-15-KR.json)은 마감 브리핑 중복 판정과 무관하다."""
    (data_dir / "brief" / "2026-10-15-KR.json").write_text("{}", encoding="utf-8")
    assert mode(kst(2026, 10, 15, 16, 5), data_dir, -7.57) == gate.ON_TIME


def test_force_and_switch_off(data_dir, monkeypatch):
    assert gate.close_mode("KR", force=True)[0] == gate.ON_TIME
    monkeypatch.setattr(gate, "CLOSE_BRIEF_ENABLED", {"KR": False})
    assert mode(kst(2026, 10, 15, 16, 5), data_dir, -7.57) == gate.SKIP


# --------------------------------------------------------------------------
# 네이버 응답
# --------------------------------------------------------------------------

def test_index_parse_signs_and_close_flag():
    row = naver.parse_index({"closePrice": "5,554.22", "compareToPreviousClosePrice": "454.59",
                             "fluctuationsRatio": "-7.57", "marketStatus": "CLOSE",
                             "localTradedAt": "2026-10-15T20:15:00+09:00"})
    assert row == {"date": "2026-10-15", "close": 5554.22, "change": -454.59,
                   "changePct": -7.57, "closed": True}
    live = naver.parse_index({"closePrice": "5,644.29", "fluctuationsRatio": "1.62",
                              "marketStatus": "OPEN", "localTradedAt": "2026-10-16T09:05:00+09:00"})
    assert live["closed"] is False


def test_leaders_skip_preferred_shares():
    data = {"stocks": [
        {"itemCode": "005930", "stockName": "삼성전자", "closePrice": "207,500", "fluctuationsRatio": "-11.51"},
        {"itemCode": "005935", "stockName": "삼성전자우", "closePrice": "160,000", "fluctuationsRatio": "-9.0"},
        {"itemCode": "000660", "stockName": "SK하이닉스", "closePrice": "1,238,000", "fluctuationsRatio": "-13.12"},
    ]}
    assert [r["name"] for r in naver.parse_leaders(data, 5)] == ["삼성전자", "SK하이닉스"]


# --------------------------------------------------------------------------
# 오늘 마감값으로 덮기
# --------------------------------------------------------------------------

STORED_KS11 = {"key": "KS11", "name": "코스피", "date": "2026-10-14", "value": 6008.81,
               "changePct": -0.44, "change5d": -12.0, "fromHigh52w": -34.07, "unit": "pt",
               "spark": [7000.0 - 50 * i for i in range(20)] + [6008.81]}


def test_today_close_replaces_the_stale_entry_and_recomputes_trend():
    """FinanceDataReader 는 마감 직후 잠정값(5,535.43)을 줬다 — 공식 5,554.22 로 덮는다."""
    naver_rows = {"KOSPI": {"date": "2026-10-15", "close": 5554.22, "change": -454.59,
                            "changePct": -7.57, "closed": True}}
    got = brief._with_today_close([STORED_KS11], naver_rows, date(2026, 10, 15))[0]
    assert (got["value"], got["changePct"], got["date"]) == (5554.22, -7.57, "2026-10-15")
    spark = STORED_KS11["spark"] + [5554.22]
    assert got["change5d"] == pytest.approx((5554.22 / spark[-6] - 1) * 100, abs=0.01)
    high = 6008.81 / (1 - 0.3407)
    assert got["fromHigh52w"] == pytest.approx((5554.22 / high - 1) * 100, abs=0.05)


def test_unclosed_or_other_day_is_left_alone():
    live = {"KOSPI": {"date": "2026-10-15", "close": 5600.0, "changePct": -6.8, "closed": False}}
    assert brief._with_today_close([STORED_KS11], live, date(2026, 10, 15))[0] is STORED_KS11
    old = {"KOSPI": {"date": "2026-10-14", "close": 6008.81, "changePct": -0.44, "closed": True}}
    assert brief._with_today_close([STORED_KS11], old, date(2026, 10, 15))[0] is STORED_KS11


# --------------------------------------------------------------------------
# 파일 · 아침 브리핑과의 연결
# --------------------------------------------------------------------------

def test_close_brief_files_and_pruning(data_dir, monkeypatch):
    monkeypatch.setattr(brief, "DATA_DIR", data_dir)
    brief.write_brief({"market": "KR", "kind": "close", "date": "2026-10-15"})
    assert (data_dir / "brief" / "latest-KR-close.json").exists()
    assert (data_dir / "brief" / "2026-10-15-KR-close.json").exists()
    assert not (data_dir / "brief" / "latest-KR.json").exists(), "장전 브리핑 파일을 덮으면 안 된다"

    old = data_dir / "brief" / "2026-08-01-KR-close.json"
    old.write_text("{}", encoding="utf-8")
    brief.prune_briefs("KR", data_dir=data_dir, today=date(2026, 10, 16))
    assert not old.exists()
    assert (data_dir / "brief" / "latest-KR-close.json").exists()


def test_next_morning_sees_yesterdays_close_brief_only(data_dir):
    def put(name, payload):
        (data_dir / "brief" / name).write_text(json.dumps(payload), encoding="utf-8")
    put("2026-10-12-KR-close.json", {"date": "2026-10-12", "headline": "옛날"})
    put("2026-10-15-KR-close.json", {"date": "2026-10-15", "headline": "검은 목요일"})
    prev = {"date": "2026-10-15"}
    got = brief.previous_close_brief("KR", date(2026, 10, 16), prev, data_dir=data_dir)
    assert got["headline"] == "검은 목요일"
    # 직전 장전 브리핑보다 오래된 마감 브리핑은 "어제"가 아니다.
    assert brief.previous_close_brief("KR", date(2026, 10, 14), {"date": "2026-10-13"},
                                      data_dir=data_dir) is None


def test_morning_prompt_shortens_yesterday_after_a_close_brief(monkeypatch):
    seen = {}
    monkeypatch.setattr(brief.llm, "available", lambda *a: True)
    monkeypatch.setattr(brief.llm, "brief_analysis", lambda p: seen.setdefault("p", p) and None)
    ctx = {"market": "KR", "session": date(2026, 10, 16), "outlook": {"score": 64, "label": "다소 우호"},
           "indices": [], "candidates": [],
           "closePrev": {"date": "2026-10-15", "headline": "검은 목요일", "threeLines": ["외국인 3.8조 매도"]}}
    brief._commentary(ctx)
    assert "[어제 장 마감 브리핑]" in seen["p"] and "외국인 3.8조 매도" in seen["p"]
    assert "2문장 이내" in seen["p"]


def test_close_prompt_context():
    ctx = {"market": "KR", "variant": "KR-close", "session": date(2026, 10, 15), "outlook": None,
           "morning": {"date": "2026-10-15", "mood": {"score": 20, "label": "약세 우려",
                                                      "reason": "필라델피아 반도체 -4.3%"},
                       "threeLines": ["아침에 한 말"]},
           "prev": {"date": "2026-10-15", "threeLines": ["아침에 한 말"]},
           "indices": [], "candidates": []}
    text = brief.context_text(ctx)
    assert "국장 마감 브리핑" in text and "15:30 에 마감" in text
    assert "[오늘 장 전망 점수" not in text
    assert "[오늘 아침 브리핑] 개장 전 전망 20점 '약세 우려'" in text
    assert "[오늘 아침 브리핑의 3가지]" in text


# --------------------------------------------------------------------------
# 만들기 · 텔레그램
# --------------------------------------------------------------------------

def _stub_network(monkeypatch, today):
    monkeypatch.setattr(brief, "now_kst", lambda: kst(today.year, today.month, today.day, 16, 10))
    monkeypatch.setattr(brief.naver_mod, "fetch_kr_indices", lambda: {
        "KOSPI": {"date": today.isoformat(), "close": 5554.22, "change": -454.59,
                  "changePct": -7.57, "closed": True},
        "KOSDAQ": {"date": today.isoformat(), "close": 760.82, "change": -63.06,
                   "changePct": -7.65, "closed": True}})
    monkeypatch.setattr(brief.naver_mod, "fetch_kr_flows", lambda: {
        "KOSPI": {"date": today.isoformat(), "foreign": -37637, "institution": 17176,
                  "individual": 13967}})
    monkeypatch.setattr(brief.naver_mod, "fetch_kr_leaders", lambda n=8: [
        {"code": "005930", "name": "삼성전자", "close": 207500.0, "changePct": -11.51,
         "date": today.isoformat()}])
    monkeypatch.setattr(brief.news_mod, "fetch_market_wrap", lambda *a, **k: [])
    monkeypatch.setattr(brief.calendar_mod, "fetch_earnings", lambda *a, **k: [])
    monkeypatch.setattr(brief.prices, "fetch_ohlcv", lambda *a, **k: None)
    monkeypatch.setattr(brief.llm, "available", lambda *a: False)


def test_build_close_brief_end_to_end(monkeypatch, data_dir):
    today = date(2026, 10, 15)
    _stub_network(monkeypatch, today)
    monkeypatch.setattr(brief, "DATA_DIR", data_dir)
    now = "2026-10-15T06:00:00Z"
    news = [
        {"title": "코스피·코스닥 7%대 급락 마감…서킷브레이커", "market": "KR", "importance": 60,
         "url": "https://k/1", "publishedAt": now, "tickers": []},
        {"title": "Ross Gerber on Tesla Roadster, Potential SpaceX Merger", "market": "US",
         "importance": 90, "url": "https://u/1", "publishedAt": now,
         "tickers": [{"code": "TSLA", "name": "Tesla"}]},
        {"title": "삼성전자 11% 폭락…외국인 매도", "market": "KR", "importance": 58,
         "url": "https://k/2", "publishedAt": now, "tickers": [{"code": "005930", "name": "삼성전자"}]},
    ]
    site = {"overview": {"indices": [dict(STORED_KS11)]}, "tickers": [], "news": news}
    b = brief.build_close_brief("KR", site)

    assert b["kind"] == "close" and b["date"] == "2026-10-15" and b["mood"] == {}
    ks = next(s for s in b["marketSnapshot"] if s["key"] == "KS11")
    assert (ks["value"], ks["changePct"]) == (5554.22, -7.57)
    assert "외국인은 3조 7,637억원어치를 순매도" in b["threeLines"][0]
    assert len(b["topNews"]) <= brief.CLOSE_NEWS_TOTAL
    assert b["topNews"][0]["url"].startswith("https://k/"), "LLM 없이도 국내 기사가 먼저"

    msg = telegram.render(b)
    assert msg.startswith("<b>🔔 국장 마감 브리핑</b>")
    assert "코스피 5,554.22 🔵 -7.57%" in msg
    assert "±2% 넘게 움직인 날에만" in msg
    assert "시총 상위: 삼성전자 🔵-11.5%" in msg
    assert "오늘 장 전망" not in msg and "차트 신호" not in msg
