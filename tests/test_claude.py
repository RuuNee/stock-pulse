"""Claude 우선 경로 (2026-11-02) — 키가 있으면 Claude, 실패하면 Gemini, 키가 없으면 예전 그대로.

실제 API 는 부르지 않는다. SDK 클라이언트를 가짜로 바꿔 끼우고 무엇을 보냈는지 본다.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from pipeline.analyze import claude, llm, summarize
from pipeline.build import site_data


class FakeClient:
    """`messages.create` / `beta.messages.create` 호출을 기록하고 정해 둔 응답을 돌려준다."""

    def __init__(self, reply=None, *, stop="end_turn", raises=None, model="claude-opus-5-5"):
        self.calls: list[dict] = []
        self.reply, self.stop, self.raises, self.model = reply, stop, raises, model
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create_beta))

    def _create(self, **kw):
        return self._answer(dict(kw, _beta=False))

    def _create_beta(self, **kw):
        return self._answer(dict(kw, _beta=True))

    def _answer(self, kw):
        self.calls.append(kw)
        if self.raises:
            raise self.raises
        reply = self.reply(kw) if callable(self.reply) else self.reply
        return SimpleNamespace(
            model=kw.get("model", self.model), stop_reason=self.stop,
            content=[SimpleNamespace(type="thinking", thinking=""),
                     SimpleNamespace(type="text", text=json.dumps(reply, ensure_ascii=False))],
            usage=SimpleNamespace(input_tokens=1000, output_tokens=500,
                                  cache_read_input_tokens=0, cache_creation_input_tokens=0))


def _bad_request(message: str):
    resp = httpx2.Response(400, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))
    return anthropic.BadRequestError(message, response=resp, body={"error": {"message": message}})


@pytest.fixture()
def keys(monkeypatch):
    """Claude·Gemini 키를 다 두고, Gemini 호출은 기록만 한다."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "g-test")
    gemini_calls = []

    def gemini(prompt, **kw):
        gemini_calls.append(kw.get("models"))
        return {"from": "gemini", "items": [], "threeLines": ["g1", "g2"]}

    monkeypatch.setattr(llm, "_post", gemini)
    llm.reset()
    yield gemini_calls
    llm.reset()


def use(monkeypatch, fake):
    monkeypatch.setattr(claude, "_get_client", lambda: fake)
    return fake


# --------------------------------------------------------------------------
# 브리핑 해설
# --------------------------------------------------------------------------

def test_brief_goes_to_claude_opus_with_schema_and_fallback(monkeypatch, keys):
    fake = use(monkeypatch, FakeClient({"headline": "h", "threeLines": ["a", "b", "c"],
                                        "analysis": [], "news": []}))
    got = llm.brief_analysis("지시", "[자료]\n숫자", {"type": "object"})
    assert got["threeLines"] == ["a", "b", "c"]
    assert keys == [], "Claude 가 답했으면 Gemini 를 부르지 않는다"

    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["_beta"]
    assert call["system"] == "지시" and call["messages"][0]["content"] == "[자료]\n숫자"
    assert call["fallbacks"] == "default" and call["betas"] == ["server-side-fallback-2026-07-01"]
    assert call["output_config"]["effort"] == "high"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert "temperature" not in call, "2026-10-21 부터 모든 모델에서 400"
    assert "thinking" not in call, "Opus 5.5 는 생각을 끌 수 없다 — 노력 수준만 조절"


@pytest.mark.parametrize("stop", ["refusal", "max_tokens"])
def test_claude_refusal_or_truncation_falls_back_to_gemini(monkeypatch, keys, stop):
    use(monkeypatch, FakeClient({"headline": "h", "threeLines": [], "analysis": [], "news": []},
                                stop=stop))
    got = llm.brief_analysis("지시", "자료", {})
    assert got["from"] == "gemini"
    assert keys == [llm.GEMINI_BRIEF_MODELS]


def test_out_of_credit_disables_claude_for_the_run(monkeypatch, keys):
    """잔액 부족은 다시 해도 같다 — 이번 실행 동안 Claude 를 끄고 Gemini 로 돈다."""
    fake = use(monkeypatch, FakeClient(raises=_bad_request("Your credit balance is too low")))
    assert llm.brief_analysis("지시", "자료", {})["from"] == "gemini"
    assert not claude.available()
    llm.explain_events([{"id": "e", "name": "n", "code": "c", "market": "KR",
                         "date": "2026-10-15", "changePct": -7.0}])
    assert len(fake.calls) == 1, "꺼진 뒤에는 Claude 를 다시 부르지 않는다"


def test_without_a_claude_key_nothing_changes(monkeypatch, keys):
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    fake = use(monkeypatch, FakeClient({}))
    assert llm.brief_analysis("지시", "자료", {})["from"] == "gemini"
    assert fake.calls == []
    assert llm.event_budget() == llm.LLM_MAX_EVENTS_PER_RUN


# --------------------------------------------------------------------------
# 이벤트 해설 · 번역
# --------------------------------------------------------------------------

def test_events_go_to_opus_with_a_bigger_budget(monkeypatch, keys):
    def reply(kw):
        return {"items": [{"id": "000660-2026-10-15", "headline": "반도체 급락", "explain": "e",
                           "sentiment": "negative", "confidence": "high", "tags": ["AI"]}]}
    fake = use(monkeypatch, FakeClient(reply))
    llm.reset()
    assert llm.event_budget() == llm.LLM_MAX_EVENTS_PER_RUN_CLAUDE > llm.LLM_MAX_EVENTS_PER_RUN
    out = llm.explain_events([{"id": "000660-2026-10-15", "name": "SK하이닉스", "code": "000660",
                               "market": "KR", "date": "2026-10-15", "changePct": -13.1,
                               "news": ["하이닉스 11% 폭락"]}])
    assert out["000660-2026-10-15"]["headline"] == "반도체 급락"
    call = fake.calls[0]
    assert call["model"] == "claude-opus-5-5" and call["_beta"]
    assert call["fallbacks"] == "default"
    assert call["output_config"]["effort"] == "low"
    assert keys == []


def test_translation_is_claude_only(monkeypatch, keys):
    fake = use(monkeypatch, FakeClient({"items": [{"i": 0, "ko": "델 주가 11% 급락"}]}))
    assert llm.translate(["Dell stock plunges 11%"]) == ["델 주가 11% 급락"]
    assert fake.calls and keys == []

    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert llm.translate(["Dell stock plunges 11%"]) == ["Dell stock plunges 11%"]
    assert keys == [], "Claude 가 없으면 번역하지 않는다 — Gemini 쿼터는 브리핑 몫"


def test_haiku_override_sends_no_server_fallback(monkeypatch, keys):
    """서버 측 거절 폴백은 Haiku 에 없다 — env 로 Haiku 로 되돌려도 폴백을 빼고 보낸다."""
    monkeypatch.setattr(llm, "CLAUDE_BULK_MODEL", "claude-haiku-5-5")
    fake = use(monkeypatch, FakeClient({"items": [{"i": 0, "ko": "델 주가 11% 급락"}]}))
    assert llm.translate(["Dell stock plunges 11%"]) == ["델 주가 11% 급락"]
    call = fake.calls[0]
    assert call["model"] == "claude-haiku-5-5" and not call["_beta"]
    assert "fallbacks" not in call


# --------------------------------------------------------------------------
# 이어받기 — 해설·번역을 실행마다 처음부터 다시 만들지 않는다
# --------------------------------------------------------------------------

def _event(eid, titles, **extra):
    return {"id": eid, "news": [{"title": t} for t in titles], "source": "rule",
            "headline": "규칙", "explain": "규칙 해설", **extra}


def test_llm_explanations_are_carried_when_news_is_unchanged():
    prev = {"events": [_event("A-2026-10-15", ["t1", "t2"], source="llm", headline="AI 요약",
                              explain="AI 해설", confidence="high"),
                       _event("B-2026-10-14", ["old"], source="llm", explain="낡은 해설")]}
    events = [_event("A-2026-10-15", ["t1", "t2"]), _event("B-2026-10-14", ["old", "new"])]
    assert site_data.carry_llm_explanations(events, prev) == 1
    assert events[0]["source"] == "llm" and events[0]["explain"] == "AI 해설"
    assert events[1]["source"] == "rule", "새 기사가 붙었으면 해설을 다시 써야 한다"


def test_already_explained_events_do_not_spend_budget(monkeypatch, keys):
    seen = []
    monkeypatch.setattr(llm, "explain_events", lambda items: seen.extend(items) or {})
    recent = "2099-01-01"
    detail = {"name": "n", "code": "c", "market": "KR", "events": [
        {"id": "x", "date": recent, "severity": 3, "changePct": -9, "news": [{"title": "a"}],
         "source": "llm"},
        {"id": "y", "date": recent, "severity": 2, "changePct": -7, "news": [{"title": "b"}],
         "source": "rule"},
    ]}
    monkeypatch.setattr(summarize, "_is_recent", lambda e: True)
    summarize.enhance_globally([detail])
    assert [i["id"] for i in seen] == ["y"]


def test_translations_are_carried_by_url():
    prev = [{"url": "u1", "title": "Dell plunges", "titleKo": "델 급락", "summary": "s",
             "summaryKo": "요약"},
            {"url": "u2", "title": "Old title", "titleKo": "옛 제목"}]
    fresh = [{"url": "u1", "title": "Dell plunges", "summary": "s"},
             {"url": "u2", "title": "Corrected title"}]
    assert site_data.carry_translations(fresh, prev) == 1
    assert fresh[0]["titleKo"] == "델 급락" and fresh[0]["summaryKo"] == "요약"
    assert "titleKo" not in fresh[1], "정정된 제목에는 옛 번역을 붙이지 않는다"


def test_cost_log_uses_price_table():
    assert claude.cost("claude-opus-5-5", 1_000_000, 1_000_000) == pytest.approx(24.0)
    assert claude.cost("claude-haiku-5-5", 1_000_000, 1_000_000) == pytest.approx(0.60)
