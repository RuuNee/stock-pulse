"""속보 감시(pipeline/watch) — 네트워크·Claude 없이 흐름을 고정한다.

실측 근거가 있는 것은 그 값으로 적는다: 11/23 엔비디아 뉴스룸 발표 13:55:00Z,
네이버 시세 응답 모양(2026-11-24), DART RSS 제목 형식.
"""

from __future__ import annotations

import itertools
import json
from datetime import datetime, timedelta, timezone

import pytest

from pipeline import config
from pipeline.watch import alerts, judge, prices, runner, sources, targets
from pipeline.watch.state import State

NOW = datetime.now(timezone.utc)

DART_RSS = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>DART</title>
<item><title>(유가)SK하이닉스 - 단일판매ㆍ공급계약체결</title>
<link>https://dart.fss.or.kr/api/link.jsp?rcpNo=20261124800001</link>
<category>유가</category><pubDate>Tue, 24 Nov 2026 09:23:00 GMT</pubDate>
<guid>https://dart.fss.or.kr/api/link.jsp?rcpNo=20261124800001</guid></item>
<item><title>(코스닥)어떤회사 - 임원ㆍ주요주주특정증권등소유상황보고서</title>
<link>https://dart.fss.or.kr/api/link.jsp?rcpNo=20261124800002</link>
<pubDate>Tue, 24 Nov 2026 09:21:00 GMT</pubDate></item>
</channel></rss>""".encode()

NEWSROOM_RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>NVIDIA</title>
<item><title>NVIDIA Board Reinstates Jensen Huang as President, CEO and Board Director</title>
<link>https://nvidianews.nvidia.com/news/nvidia-board-reinstates-jensen-huang</link>
<pubDate>Mon, 23 Nov 2026 13:55:00 GMT</pubDate></item></channel></rss>""".encode()

NVDA = {"market": "US", "code": "NVDA", "name": "엔비디아", "reason": "CEO 사임 후속",
        "kind": "이슈", "aliases": ["NVIDIA", "Nvidia", "젠슨 황"]}
HYNIX = {"market": "KR", "code": "000660", "name": "SK하이닉스", "reason": "엔비디아 연동",
         "kind": "연관", "aliases": ["하이닉스"]}

VERDICT = {"direction": "호재", "strength": 3, "important": True, "new_fact": True,
           "title_ko": "엔비디아 이사회, 젠슨 황 CEO 복귀 결정",
           "line": "사임 11일 만의 복귀로 리더십 불확실성 해소", "related": ["SK하이닉스"]}


# --------------------------------------------------------------------------
# 소스 파싱
# --------------------------------------------------------------------------


def test_dart_title_split_and_material():
    items = sources.parse_dart(DART_RSS)
    assert [it["id"] for it in items] == ["dart:20261124800001", "dart:20261124800002"]
    first = items[0]
    assert first["meta"]["cls"] == "유가" and first["meta"]["corp"] == "SK하이닉스"
    assert first["meta"]["report"] == "단일판매ㆍ공급계약체결"
    assert first["publishedAt"] == datetime(2026, 11, 24, 9, 23, tzinfo=timezone.utc)
    assert sources.dart_material(first["meta"]["report"])
    assert not sources.dart_material(items[1]["meta"]["report"])   # 임원 지분 보고 — 절차 서식
    assert sources.dart_listed(first)


def test_newsroom_release_time_is_kept():
    items = sources.parse_feed(NEWSROOM_RSS, source="newsroom:NVDA", official=True, market="US")
    assert items[0]["publishedAt"] == datetime(2026, 11, 23, 13, 55, tzinfo=timezone.utc)
    assert sources.strong_release(items[0])            # "CEO", "Reinstat" — 판정 없이도 보낸다


def test_wire_tickers():
    item = {"title": "YYForce (NASDAQ: YFOR) Launches Robot", "summary": "Foo (NYSE: XOM) said"}
    assert sources.wire_tickers(item) == ["YFOR", "XOM"]
    assert sources.wire_tickers({"title": "Huawei wins award", "summary": ""}) == []


def test_matcher_rules():
    m = sources.Matcher([NVDA, HYNIX, {"market": "KR", "code": "003550", "name": "LG",
                                       "aliases": []}])
    dart = sources.parse_dart(DART_RSS)[0]
    assert [t["code"] for t in m.match(dart)] == ["000660"]
    room = {"source": "newsroom:NVDA", "title": "Holiday post", "meta": {"ticker": "NVDA"}}
    assert [t["code"] for t in m.match(room)] == ["NVDA"]
    news = {"source": "wsj_markets", "title": "Nvidia shares jump as Huang returns", "meta": {}}
    assert [t["code"] for t in m.match(news)] == ["NVDA"]
    kr = {"source": "mk_stock", "title": "젠슨 황 복귀에 하이닉스 12% 급등", "meta": {}}
    assert {t["code"] for t in m.match(kr)} == {"NVDA", "000660"}
    # 두 글자 영문 이름(LG)은 흔한 낱말과 겹쳐서 쓰지 않는다
    assert m.match({"source": "x", "title": "LG results beat", "meta": {}}) == []
    # 'Nvidia' 가 다른 낱말 속에 있으면 안 붙는다
    assert m.match({"source": "x", "title": "Nvidiax launches", "meta": {}}) == []


# --------------------------------------------------------------------------
# 시세
# --------------------------------------------------------------------------

US_PAYLOAD = {"datas": [
    {"reutersCode": "NVDA.O", "symbolCode": "NVDA", "closePrice": "165.05",
     "fluctuationsRatio": "31.48", "marketStatus": "CLOSE",
     "overMarketPriceInfo": {"tradingSessionType": "PRE_MARKET", "overMarketStatus": "OPEN",
                             "overPrice": "157.10", "fluctuationsRatio": "-4.82"}},
    {"reutersCode": "BRKb", "symbolCode": "BRK B", "closePrice": "500.00",
     "fluctuationsRatio": "0.10", "marketStatus": "OPEN"},
]}
KR_PAYLOAD = {"datas": [
    {"itemCode": "005930", "closePrice": "182,900", "fluctuationsRatio": "3.04",
     "marketStatus": "CLOSE",
     "overMarketPriceInfo": {"tradingSessionType": "AFTER_MARKET", "overMarketStatus": "CLOSE",
                             "overPrice": "182,900"}},
]}


def test_parse_quotes_sessions():
    us = prices.parse_us(US_PAYLOAD)
    nvda, code = us["NVDA"]
    assert (nvda.session, nvda.price, nvda.day_pct, code) == ("pre", 157.10, -4.82, "NVDA.O")
    assert us["BRK.B"][0].session == "regular"
    kr = prices.parse_kr(KR_PAYLOAD)["005930"]
    assert (kr.session, kr.price) == ("closed", 182900.0)


def test_us_code_resolution_remembers_naver_code():
    class F:
        urls: list[str] = []

        def json(self, url):
            self.urls.append(url)
            return US_PAYLOAD

    known: dict[str, str] = {}
    got = prices.fetch_us(F(), ["NVDA"], known)
    assert "NVDA.O,NVDA" in F.urls[0]          # 나스닥 .O 와 맨 티커를 같이 물어본다
    assert got["NVDA"].price == 157.10 and known == {"NVDA": "NVDA.O"}
    assert prices.us_candidates("BRK.B") == ["BRKb", "BRKb.O"]


def test_move_detector_windows_extend_and_reverse():
    d = prices.MoveDetector(one=2.0, five=3.5, step=3.0, hold_min=60)
    t = 1000.0
    assert d.update("US:NVDA", 136.0, t, "pre") is None          # 기록이 짧으면 판정하지 않는다
    assert d.update("US:NVDA", 136.1, t + 30, "pre") is None
    mv = d.update("US:NVDA", 149.56, t + 65, "pre")             # 11/23 08:54→08:55
    assert mv and mv.kind == "new" and mv.direction == "up" and mv.window == "1분"
    assert d.update("US:NVDA", 150.5, t + 70, "pre") is None     # 같은 방향, 3%p 안 — 조용히
    ext = d.update("US:NVDA", 155.0, t + 130, "pre")
    assert ext and ext.kind == "extend"
    rev = d.update("US:NVDA", 150.0, t + 190, "pre")             # 1분에 -3.2%
    assert rev and rev.kind == "reverse" and rev.direction == "down"


def test_move_detector_resets_on_session_change():
    d = prices.MoveDetector(one=2.0, five=3.5)
    d.update("US:NVDA", 159.0, 0, "pre")
    d.update("US:NVDA", 159.0, 61, "pre")
    # 정규장 시가 갭은 급변이 아니다 — 세션이 바뀌면 기록을 비운다
    assert d.update("US:NVDA", 167.0, 62, "regular") is None
    assert d.update("US:NVDA", 167.0, 63, "closed") is None


# --------------------------------------------------------------------------
# 상태
# --------------------------------------------------------------------------


def test_state_seen_hot_and_persistence(tmp_path):
    path = tmp_path / "state.json"
    s = State(path)
    assert not s.known_source("dart")
    assert s.mark_seen("dart", ["a", "b", "a"]) == {"a", "b"}
    assert s.mark_seen("dart", ["b", "c"]) == {"c"}
    assert s.seen["dart"] == ["a", "b", "c"]
    s.set_targets([NVDA], NOW)
    assert s.add_hot(HYNIX, 24, NOW) and not s.add_hot(NVDA, 24, NOW)
    s.save()
    again = State(path)
    assert again.known_source("dart") and again.mark_seen("dart", ["c"]) == set()
    assert {t["code"] for t in again.active_targets(NOW)} == {"NVDA", "000660"}
    assert {t["code"] for t in again.active_targets(NOW + timedelta(hours=25))} == {"NVDA"}


# --------------------------------------------------------------------------
# 대상 선정
# --------------------------------------------------------------------------


def test_target_schedule():
    kst = config.KST
    last = datetime(2026, 11, 24, 7, 25, tzinfo=kst)
    assert not targets.due(datetime(2026, 11, 24, 12, 0, tzinfo=kst), last)
    assert targets.due(datetime(2026, 11, 24, 15, 41, tzinfo=kst), last)     # 15:40 슬롯
    assert targets.due(datetime(2026, 11, 24, 12, 0, tzinfo=kst), None)
    assert targets.due(datetime(2026, 11, 25, 6, 0, tzinfo=kst), last)       # 10시간 넘음


def test_target_validation_fixes_codes():
    raw = [
        {"market": "KR", "code": "", "name": "SK하이닉스", "reason": "r", "kind": "연관", "aliases": []},
        {"market": "KR", "code": "12AB", "name": "없는회사", "reason": "r", "kind": "이슈", "aliases": []},
        {"market": "US", "code": "nvda", "name": "NVIDIA", "reason": "r", "kind": "이슈", "aliases": ["젠슨 황"]},
        {"market": "US", "code": "NVDA", "name": "dup", "reason": "r", "kind": "이슈", "aliases": []},
        {"market": "US", "code": "BAD TICKER", "name": "x", "reason": "r", "kind": "이슈", "aliases": []},
    ]
    got = targets.validate(raw, None)
    assert [(t["market"], t["code"]) for t in got] == [("KR", "000660"), ("US", "NVDA")]
    assert "엔비디아" in got[1]["aliases"] and "젠슨 황" in got[1]["aliases"]


def test_target_fallback_without_claude():
    news = {"items": [{"publishedAt": (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                       "tickers": [{"market": "US", "code": "NVDA"}]}] * 3}
    index = {"items": [{"market": "KR", "code": "000660", "name": "SK하이닉스", "exchange": "KOSPI",
                        "changePct": 10.1}]}
    got = targets.fallback(news, index, NOW)
    reasons = {t["code"]: t["reason"] for t in got}
    assert reasons["NVDA"] == "최근 24시간 뉴스 3건" and reasons["000660"] == "오늘 +10.1%"


# --------------------------------------------------------------------------
# 알림 문구
# --------------------------------------------------------------------------


def test_render_puts_verdict_first():
    inc = {"key": "US:NVDA", "market": "US", "code": "NVDA", "name": "엔비디아",
           "reason": "CEO 사임 후속 — 감시 대상", "verdict": VERDICT,
           "move": {"direction": "up", "pct": 10.0, "window": "1분", "price": 149.56,
                    "session": "pre", "currency": "USD", "dayPct": 19.1},
           "release": {"title": "NVIDIA Board Reinstates <Huang>", "url": "https://x/?a=1&b=2",
                       "official": True, "publishedAt": "2026-11-23T13:55:00Z",
                       "seenAt": "2026-11-23T13:55:04Z"}}
    text = alerts.render(inc)
    first = text.splitlines()[0]
    assert first.startswith("🔴 <b>호재</b> · 강") and "엔비디아" in first and "<code>NVDA</code>" in first
    assert "1분 새 +10.0% · 프리마켓 $149.56 (전일 대비 +19.1%)" in text
    assert "&lt;Huang&gt;" in text and "↳ 엔비디아 이사회" in text
    assert "발표 22:55:00 · 감지 22:55:04 (+4초)" in text
    assert 'href="https://x/?a=1&amp;b=2"' in text


def test_render_move_only_and_market_wide():
    inc = {"key": "KR:000660", "market": "KR", "code": "000660", "name": "SK하이닉스",
           "move": {"direction": "down", "pct": -2.5, "window": "1분", "price": 1113000,
                    "session": "after", "currency": "KRW", "dayPct": None}}
    text = alerts.render(inc)
    assert text.startswith("🔻 <b>급락</b> · 원인 확인 중") and "1,113,000원" in text
    mkt = {"key": "MKT:abc", "market": "MKT", "code": "abc", "name": "시장 전체",
           "verdict": {**VERDICT, "direction": "악재"}}
    out = alerts.render(mkt)
    assert out.startswith("🔵 <b>악재</b>") and "<code>" not in out


# --------------------------------------------------------------------------
# 처리 흐름 (가짜 발송·판정)
# --------------------------------------------------------------------------


class FakeSender:
    def __init__(self):
        self.posts: list[dict] = []
        self.edits: list[dict] = []
        self._ids = itertools.count(1)

    def post(self, text, *, silent=False, reply_to=None):
        self.posts.append({"text": text, "silent": silent, "reply_to": reply_to})
        return {"1": next(self._ids)}

    def edit(self, ids, text):
        self.edits.append({"ids": ids, "text": text})
        return True


@pytest.fixture
def watcher(tmp_path, monkeypatch):
    w = runner.Watcher(state_path=tmp_path / "state.json", fetcher=object(), sender=FakeSender())
    w.state.set_targets([NVDA, HYNIX], NOW)
    w.rebuild_matcher()
    monkeypatch.setattr(w.budget, "allow", lambda kind: True)
    return w


def _item(title, *, source="newsroom:NVDA", official=True, minutes_ago=0, meta=None):
    return {"id": f"{source}:{title}", "source": source, "official": official, "title": title,
            "summary": "", "url": "https://example.com/n", "market": "US",
            "publishedAt": NOW - timedelta(minutes=minutes_ago), "seenAt": NOW,
            "meta": meta if meta is not None else ({"ticker": "NVDA"} if source.startswith("newsroom") else {})}


def test_first_poll_seeds_then_new_items_queue(watcher):
    items = sources.parse_feed(NEWSROOM_RSS, source="newsroom:NVDA", official=True)
    watcher.ingest("newsroom:NVDA", items)
    assert watcher.queue.empty()                       # 처음 본 것은 지난 것으로만 기록
    fresh = {**items[0], "id": "newsroom:NVDA:new"}
    watcher.ingest("newsroom:NVDA", [fresh, *items])
    priority, _, kind, payload = watcher.queue.get_nowait()
    assert (priority, kind, payload["id"]) == (runner.PRIO_OFFICIAL, "item", "newsroom:NVDA:new")


def test_official_release_alert_with_verdict(watcher, monkeypatch):
    monkeypatch.setattr(judge, "quick", lambda ctx, **kw: dict(VERDICT))
    watcher.on_item(_item("NVIDIA Board Reinstates Jensen Huang as CEO"))
    assert len(watcher.sender.posts) == 1
    post = watcher.sender.posts[0]
    assert post["text"].startswith("🔴 <b>호재</b>") and not post["silent"]
    assert watcher.state.alerts[-1]["direction"] == "호재"
    # 같은 제목이 다시 와도(다른 소스) 두 번 보내지 않는다
    watcher.on_item(_item("NVIDIA Board Reinstates Jensen Huang as CEO", source="prnewswire",
                          meta={"sourceName": "PR Newswire"}))
    assert len(watcher.sender.posts) == 1


def test_unimportant_release_is_dropped(watcher, monkeypatch):
    monkeypatch.setattr(judge, "quick", lambda ctx, **kw: {**VERDICT, "important": False,
                                                           "direction": "중립", "strength": 1})
    watcher.on_item(_item("Merry Making: Play, Build and Create With NVIDIA Technologies"))
    assert watcher.sender.posts == []


def test_release_without_claude_uses_keywords(watcher, monkeypatch):
    monkeypatch.setattr(watcher.budget, "allow", lambda kind: False)
    watcher.on_item(_item("Holiday gift guide"))
    assert watcher.sender.posts == []
    watcher.on_item(_item("NVIDIA Board Reinstates Jensen Huang as CEO"))
    assert watcher.sender.posts[0]["text"].startswith("⏳ <b>판정 중</b>")
    kinds = []
    while not watcher.queue.empty():
        kinds.append(watcher.queue.get_nowait()[2])
    assert "rejudge" in kinds


def test_stale_release_is_not_alerted(watcher, monkeypatch):
    monkeypatch.setattr(judge, "quick", lambda ctx, **kw: dict(VERDICT))
    watcher.on_item(_item("NVIDIA Board Reinstates Jensen Huang as CEO", minutes_ago=45))
    assert watcher.sender.posts == []


def test_move_first_then_cause_attaches(watcher, monkeypatch):
    monkeypatch.setattr(judge, "quick", lambda ctx, **kw: dict(VERDICT))
    move = prices.Move("US:NVDA", "up", 10.0, "1분", 149.56, "pre", "new")
    quote = prices.Quote("US", "NVDA", 149.56, 19.1, "pre", "USD")
    watcher.on_move(move, quote)
    assert watcher.sender.posts[0]["text"].startswith("🔺 <b>급등</b> · 원인 확인 중")
    watcher.on_item(_item("NVIDIA Board Reinstates Jensen Huang as CEO"))
    assert watcher.sender.edits[-1]["text"].startswith("🔴 <b>호재</b>")
    reply = watcher.sender.posts[-1]
    assert reply["silent"] and "원인 확인" in reply["text"] and reply["reply_to"] == {"1": 1}
    # 같은 방향 추가 상승은 같은 메시지의 주가 줄만 고친다
    watcher.on_move(prices.Move("US:NVDA", "up", 4.0, "5분", 160.0, "pre", "extend"), quote)
    assert len(watcher.sender.posts) == 2 and "$160.00" in watcher.sender.edits[-1]["text"]


def test_move_finds_recent_cause(watcher, monkeypatch):
    monkeypatch.setattr(judge, "quick", lambda ctx, **kw: dict(VERDICT))
    monkeypatch.setattr(watcher.budget, "allow", lambda kind: False)
    watcher.on_item(_item("Holiday gift guide"))                     # 판정 못 해 그냥 지나감
    watcher.recent.append(_item("NVIDIA Board Reinstates Jensen Huang as CEO"))
    monkeypatch.setattr(watcher.budget, "allow", lambda kind: True)
    watcher.on_move(prices.Move("US:NVDA", "up", 10.0, "1분", 149.56, "pre", "new"),
                    prices.Quote("US", "NVDA", 149.56, 19.1, "pre", "USD"))
    text = watcher.sender.posts[-1]["text"]
    assert text.startswith("🔴 <b>호재</b>") and "Reinstates" in text


def test_target_news_batches_per_company(watcher, monkeypatch):
    calls = []
    monkeypatch.setattr(judge, "quick", lambda ctx, **kw: calls.append(ctx) or dict(VERDICT))
    for i in range(3):
        watcher.on_item(_item(f"Nvidia surges after Huang return {i}", source="wsj_markets",
                              official=False, meta={"sourceName": "WSJ"}))
    watcher.flush_target_news()
    assert len(calls) == 1 and "같은 종목 다른 기사" in calls[0]
    assert len(watcher.sender.posts) == 1


def test_screen_confirm_alerts_and_adds_hot_target(watcher, monkeypatch):
    item = _item("(유가)삼성전자 - 단일판매ㆍ공급계약체결", source="dart",
                 meta={"cls": "유가", "corp": "삼성전자", "report": "단일판매ㆍ공급계약체결"})
    watcher.on_item(item)
    assert watcher.screen_buf == [item]          # 대상 밖 중요 공시 → 선별 대기
    monkeypatch.setattr(runner.claude, "available", lambda model=None: True)
    monkeypatch.setattr(judge, "screen", lambda numbered, recent: [
        {"n": 1, "impact": 4, "fact": True, "direction": "호재",
         "companies": [{"market": "KR", "code": "005930", "name": "삼성전자"}]}])
    monkeypatch.setattr(judge, "confirm", lambda ctx: {
        **VERDICT, "send": True, "companies": [{"market": "KR", "code": "005930", "name": "삼성전자"}]})
    watcher.screen_once()
    _, _, kind, payload = watcher.queue.get_nowait()
    assert kind == "alert"
    watcher.handle(kind, payload)
    assert watcher.sender.posts[-1]["text"].startswith("🔴 <b>호재</b>")
    assert "005930" in {t["code"] for t in watcher.state.active_targets()}


def test_routine_dart_and_untagged_wire_skip_screening(watcher):
    watcher.on_item(_item("(코스닥)어떤회사 - 임원ㆍ주요주주특정증권등소유상황보고서", source="dart",
                          meta={"cls": "코스닥", "corp": "어떤회사",
                                "report": "임원ㆍ주요주주특정증권등소유상황보고서"}))
    watcher.on_item(_item("Huawei wins award", source="prnewswire", meta={}))
    assert watcher.screen_buf == []


def test_budget_caps(tmp_path, monkeypatch):
    s = State(tmp_path / "s.json")
    monkeypatch.setattr(runner.claude, "available", lambda model=None: True)
    spent = {"v": 0.0}
    monkeypatch.setattr(judge.claude, "total_cost", lambda: spent["v"])
    b = judge.Budget(s)
    assert b.allow("screen") and b.allow("quick")
    spent["v"] = config.WATCH_DAILY_BUDGET_USD
    assert not b.allow("screen") and b.allow("quick")      # 즉시 판정은 1.5배까지
    spent["v"] = config.WATCH_DAILY_BUDGET_USD * 1.5
    assert not b.allow("quick")
    s.budget["confirms"] = config.WATCH_CONFIRM_MAX_PER_DAY
    spent["v"] = 0.0
    b2 = judge.Budget(s)
    assert not b2.allow("confirm")


# --------------------------------------------------------------------------
# 텔레그램·Claude 연결부
# --------------------------------------------------------------------------


def test_telegram_post_and_edit(monkeypatch):
    from pipeline.notify import telegram
    calls = []
    monkeypatch.setattr(telegram, "_call", lambda token, method, payload: calls.append(
        (method, payload)) or {"message_id": 77})
    ids = telegram.post("hi", silent=True, chat_ids=["1", "2"], token="t")
    assert ids == {"1": 77, "2": 77}
    assert calls[0][1]["disable_notification"] is True and calls[0][1]["parse_mode"] == "HTML"
    assert telegram.post("again", reply_to={"1": 77}, chat_ids=["1"], token="t")
    assert calls[-1][1]["reply_parameters"]["message_id"] == 77
    assert telegram.edit({"1": 77}, "fixed", token="t")
    assert calls[-1][0] == "editMessageText"


def test_watch_chat_ids_override(monkeypatch):
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1,2")
    monkeypatch.delenv("WATCH_TELEGRAM_CHAT_ID", raising=False)
    assert config.watch_chat_ids() == ["1", "2"]
    monkeypatch.setenv("WATCH_TELEGRAM_CHAT_ID", "9")
    assert config.watch_chat_ids() == ["9"]


def test_claude_per_call_timeout(monkeypatch):
    from pipeline.analyze import claude
    seen = {}

    class Resp:
        stop_reason = "end_turn"
        model = "claude-haiku-5-5"
        usage = None
        content = [type("B", (), {"type": "text", "text": json.dumps({"ok": True})})()]

    class Client:
        def __init__(self, opts=None):
            self.opts = opts or {}
            self.messages = self

        def with_options(self, **opts):
            seen.update(opts)
            return Client(opts)

        def create(self, **params):
            seen["params"] = params
            return Resp()

    monkeypatch.setattr(claude, "available", lambda model=None: True)
    monkeypatch.setattr(claude, "_get_client", lambda: Client())
    got = claude.ask_json("s", "u", {"type": "object"}, model="claude-haiku-5-5", effort="low",
                          max_tokens=10, timeout=5, retries=0)
    assert got == {"ok": True} and seen["timeout"] == 5 and seen["max_retries"] == 0


def test_routine_dart_of_target_is_not_judged(watcher, monkeypatch):
    calls = []
    monkeypatch.setattr(judge, "quick", lambda ctx, **kw: calls.append(ctx) or dict(VERDICT))
    watcher.on_item(_item("(유가)SK하이닉스 - 임원ㆍ주요주주특정증권등소유상황보고서", source="dart",
                          meta={"cls": "유가", "corp": "SK하이닉스",
                                "report": "임원ㆍ주요주주특정증권등소유상황보고서"}))
    assert calls == [] and watcher.sender.posts == []
    watcher.on_item(_item("(유가)SK하이닉스 - 단일판매ㆍ공급계약체결", source="dart",
                          meta={"cls": "유가", "corp": "SK하이닉스", "report": "단일판매ㆍ공급계약체결"}))
    assert len(calls) == 1 and watcher.sender.posts[0]["text"].startswith("🔴 <b>호재</b>")
