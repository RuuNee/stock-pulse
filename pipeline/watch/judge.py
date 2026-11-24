"""속보 판정 — Claude 에게 호재·악재, 중요도, 감시 대상을 묻는다.

* quick   대상 종목 소식 하나 → 호재/악재·강도·한 줄 이유. Haiku, 몇 초 제한.
* screen  대상 밖 새 항목 묶음 → 영향 큰 것만 추린다. Haiku.
* confirm 추린 것 하나 → 알릴지 최종 결정과 문구. Opus.
* targets 감시 대상 고르기(targets.py 가 부른다). Opus.

키가 없거나 하루 상한을 넘으면 None 을 돌려주고, 부르는 쪽은 규칙으로 계속 간다.
"""

from __future__ import annotations

from datetime import datetime

from ..analyze import claude
from ..config import (
    KST,
    WATCH_CONFIRM_MAX_PER_DAY,
    WATCH_DAILY_BUDGET_USD,
    WATCH_DEEP_MODEL,
    WATCH_QUICK_MODEL,
    WATCH_QUICK_TIMEOUT_SEC,
    WATCH_SCREEN_MODEL,
)
from ..util import log

_DIRECTIONS = ["호재", "악재", "중립"]


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}


_COMPANY = _obj({
    "market": {"type": "string", "enum": ["KR", "US"]},
    "code": {"type": "string"},
    "name": {"type": "string"},
})

QUICK_SCHEMA = _obj({
    "direction": {"type": "string", "enum": _DIRECTIONS},
    "strength": {"type": "integer", "enum": [1, 2, 3]},
    "important": {"type": "boolean"},
    "new_fact": {"type": "boolean"},
    "title_ko": {"type": "string"},
    "line": {"type": "string"},
    "related": {"type": "array", "items": {"type": "string"}},
})

SCREEN_SCHEMA = _obj({"items": {"type": "array", "items": _obj({
    "n": {"type": "integer"},
    "impact": {"type": "integer", "enum": [3, 4, 5]},
    "fact": {"type": "boolean"},
    "direction": {"type": "string", "enum": _DIRECTIONS},
    "companies": {"type": "array", "items": _COMPANY},
})}})

CONFIRM_SCHEMA = _obj({
    "send": {"type": "boolean"},
    "direction": {"type": "string", "enum": _DIRECTIONS},
    "strength": {"type": "integer", "enum": [1, 2, 3]},
    "title_ko": {"type": "string"},
    "line": {"type": "string"},
    "companies": {"type": "array", "items": _COMPANY},
    "related": {"type": "array", "items": {"type": "string"}},
})

_QUICK_SYSTEM = """너는 한국 개인 투자자에게 주식 속보를 알리는 애널리스트다. 방금 들어온 소식이 \
해당 회사 주가에 어떤 영향을 줄지 바로 판정해 정해진 JSON 하나로 답한다.

- direction: 주가에 좋으면 "호재", 나쁘면 "악재", 영향이 작거나 좋고 나쁨이 섞이면 "중립".
- strength: 3 = 주가가 크게(대략 ±5% 이상) 움직일 만함, 2 = 눈에 띄게(±2~5%), 1 = 작음.
- important: 투자자가 지금 알아야 할 새 소식이면 true. 홍보·행사·캠페인·일상 공시·시황 요약·\
전망 칼럼이면 false.
- new_fact: "이미 알린 내용"과 다른 새 사실이면 true, 같은 사실을 다시 전하는 기사면 false. \
이미 알린 내용이 없으면 true.
- title_ko: 소식 제목을 자연스러운 한국어 한 줄로. 이미 한국어면 다듬기만 한다.
- line: 왜 호재·악재인지 한 문장, 50자 안팎. 근거와 숫자 위주, 과장 금지. 주가가 이미 크게 \
움직였으면 그 점을 짧게 반영한다.
- related: 이 소식에 같이 움직일 만한 다른 종목 이름 최대 3개(국장·미장 모두). 없으면 빈 배열."""

_SCREEN_SYSTEM = """너는 주식 속보 데스크다. 방금 들어온 기사·공시·보도자료 목록에서 주가를 크게 \
움직일 새 소식만 골라 JSON 으로 답한다.

- impact: 5 = 시장 전체나 대형주가 크게 움직일 소식, 4 = 개별 종목이 ±5% 이상 움직일 만한 소식, \
3 = 눈에 띄는 영향. 3 미만은 적지 않는다(대부분의 항목은 빠져야 정상이다).
- fact: 새로 확인된 사실(발표·공시·확정 보도)이면 true. 시황 요약·전망·칼럼·지난 일 해설·\
루머·추측, "이미 알린 소식"의 재탕이면 false.
- direction: 주 종목(없으면 시장)에 "호재"/"악재"/"중립".
- companies: 영향받는 상장사. market 은 KR 또는 US, code 는 미장 티커·국장 6자리(모르면 빈 \
문자열), name 은 회사 이름.
- n: 목록 번호 그대로."""

_CONFIRM_SYSTEM = """너는 주식 속보 알림의 마지막 확인 담당이다. 1차 선별을 통과한 소식 하나를 \
보고 한국 개인 투자자에게 지금 알림을 보낼지 정해 JSON 으로 답한다.

send 는 이럴 때만 true: (1) 공식 발표·공시나 믿을 만한 매체의 확정 보도로 확인된 새 사실이고 \
(2) 관련 종목이나 시장이 크게 움직일 만하다. 루머·추측·의견·지난 일 재탕·이미 알린 소식은 false.
- direction: 주 종목 기준 호재/악재/중립. strength: 3 = 크게(±5% 이상), 2 = 눈에 띄게, 1 = 작게.
- title_ko: 한국어 제목 한 줄. line: 왜 호재·악재인지 한 문장(50자 안팎), 근거 위주.
- companies: 주로 영향받는 상장사, 첫 번째가 주 종목. code 는 미장 티커·국장 6자리, 모르면 빈 문자열.
- related: 같이 움직일 만한 다른 종목 이름 최대 3개."""


# --------------------------------------------------------------------------
# 비용 상한
# --------------------------------------------------------------------------


def _today() -> str:
    return datetime.now(KST).date().isoformat()


class Budget:
    """오늘(KST) 쓴 Claude 비용. 재시작해도 상태 파일로 이어진다.

    `claude.total_cost()` 는 이 프로세스 누적이라, 오늘 시작 시점 값을 빼고 지난
    프로세스가 오늘 쓴 몫(offset)을 더한다.
    """

    def __init__(self, state):
        self.state = state
        self._base = claude.total_cost()
        if state.budget.get("day") != _today():
            state.budget = {"day": _today(), "spent": 0.0, "confirms": 0}
        self._offset = float(state.budget.get("spent") or 0.0)

    def _roll(self) -> None:
        if self.state.budget.get("day") != _today():
            self.state.budget = {"day": _today(), "spent": 0.0, "confirms": 0}
            self._offset = 0.0
            self._base = claude.total_cost()

    def spent(self) -> float:
        self._roll()
        return self._offset + (claude.total_cost() - self._base)

    def allow(self, kind: str) -> bool:
        if not claude.available():
            return False
        cap = WATCH_DAILY_BUDGET_USD * (1.5 if kind == "quick" else 1.0)
        if self.spent() >= cap:
            return False
        if kind == "confirm" and self.state.budget.get("confirms", 0) >= WATCH_CONFIRM_MAX_PER_DAY:
            return False
        return True

    def note_confirm(self) -> None:
        self.state.budget["confirms"] = int(self.state.budget.get("confirms", 0)) + 1

    def sync(self) -> None:
        self.state.budget["spent"] = round(self.spent(), 4)


# --------------------------------------------------------------------------
# 판정
# --------------------------------------------------------------------------


def quick(context: str, *, timeout: float = WATCH_QUICK_TIMEOUT_SEC) -> dict | None:
    data = claude.ask_json(_QUICK_SYSTEM, context, QUICK_SCHEMA, model=WATCH_QUICK_MODEL,
                           effort="low", max_tokens=2000, timeout=timeout, retries=0)
    return _clean_verdict(data)


def screen(numbered: str, recent_alerts: str) -> list[dict]:
    body = numbered + (f"\n\n[이미 알린 소식]\n{recent_alerts}" if recent_alerts else "")
    data = claude.ask_json(_SCREEN_SYSTEM, body, SCREEN_SCHEMA, model=WATCH_SCREEN_MODEL,
                           effort="low", max_tokens=6000, timeout=60, retries=1)
    if not data:
        return []
    return [row for row in data.get("items") or [] if isinstance(row, dict)]


def confirm(context: str) -> dict | None:
    data = claude.ask_json(_CONFIRM_SYSTEM, context, CONFIRM_SCHEMA, model=WATCH_DEEP_MODEL,
                           effort="low", max_tokens=6000, fallback=True, timeout=90, retries=1)
    verdict = _clean_verdict(data)
    if verdict is not None:
        verdict["send"] = bool(data.get("send"))
        verdict["companies"] = [c for c in data.get("companies") or [] if isinstance(c, dict)]
    return verdict


def _clean_verdict(data: dict | None) -> dict | None:
    if not data or data.get("direction") not in _DIRECTIONS:
        if data is not None:
            log.warn("watch: 판정 응답이 모양이 다릅니다 — 버립니다")
        return None
    strength = data.get("strength")
    return {
        "direction": data["direction"],
        "strength": strength if strength in (1, 2, 3) else 1,
        "important": bool(data.get("important", True)),
        "new_fact": bool(data.get("new_fact", True)),
        "title_ko": str(data.get("title_ko") or "").strip()[:160],
        "line": str(data.get("line") or "").strip()[:200],
        "related": [str(r).strip() for r in data.get("related") or [] if str(r).strip()][:3],
    }
