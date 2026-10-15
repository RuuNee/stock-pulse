"""Google Gemini (free tier) client for the pipeline's LLM features.

Three jobs: (1) beginner-friendly cause summaries for chart events, (2) the
brief's market commentary (headline, 3 points, analysis, news picks),
(3) auto-translating foreign (US) news to Korean.

Free-tier quotas are per-minute and per-day **per model**, so bulk work (event
summaries, translation) and the brief use different models — see
`config.GEMINI_BULK_MODEL`. Each model keeps its own failure state: a dead bulk
model must not take the brief down with it. Calls are batched and throttled,
and every failure degrades gracefully (returns None → callers fall back to
rules). Raw REST via requests — no SDK dependency.
"""

from __future__ import annotations

import json
import time

import requests

from ..config import (
    GEMINI_BRIEF_MAX_TOKENS,
    GEMINI_BRIEF_THINKING,
    GEMINI_BULK_MODEL,
    GEMINI_DELAY_SEC,
    GEMINI_MAX_TOKENS,
    GEMINI_MODEL,
    LLM_ENABLED,
    LLM_EVENT_BATCH,
    LLM_MAX_EVENTS_PER_RUN,
    gemini_key,
)
from ..util import log

_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Global per-run state.
_budget = 0          # remaining event summaries allowed this run
_calls = 0
_disabled: set[str] = set()       # models that hard-failed this run
_consec_429: dict[str, int] = {}  # per-model consecutive rate-limit hits

_MAX_CONSEC_429 = 3  # after this many, give up on that model for the whole run


def available(model: str | None = None) -> bool:
    return (LLM_ENABLED and gemini_key() is not None
            and (model or GEMINI_MODEL) not in _disabled)


def reset() -> None:
    """Call once at the start of a run."""
    global _budget, _calls
    _budget = LLM_MAX_EVENTS_PER_RUN
    _calls = 0
    _disabled.clear()
    _consec_429.clear()


def _post(prompt: str, *, model: str | None = None, max_tokens: int = GEMINI_MAX_TOKENS,
          thinking: int = 0, temperature: float = 0.3, retries: int = 2):
    """One Gemini call. Returns parsed JSON (dict|list) or None."""
    global _calls
    model = model or GEMINI_MODEL
    key = gemini_key()
    if not key or model in _disabled:
        return None

    url = _ENDPOINT.format(model=model)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
            # 2.5 계열은 생각하는 모델이다. 대량 작업은 꺼서 빠르고 깨끗한 JSON 을
            # 받고, 원인을 엮어 써야 하는 브리핑 해설에만 예산을 준다.
            "thinkingConfig": {"thinkingBudget": thinking},
        },
    }

    for attempt in range(retries + 1):
        time.sleep(GEMINI_DELAY_SEC)  # throttle to stay under free-tier RPM
        try:
            r = requests.post(url, params={"key": key}, json=body, timeout=120)
        except Exception as exc:
            log.warn(f"gemini[{model}] request error: {exc}")
            continue

        if r.status_code == 429:
            _consec_429[model] = _consec_429.get(model, 0) + 1
            # 어느 쿼터(분당/일일)에 걸렸는지 남긴다. 예전 로그는 "429" 만 있어서
            # 브리핑이 왜 규칙 요약으로 나갔는지 나중에 알 수 없었다.
            log.warn(f"gemini[{model}] rate-limited (429): {_quota_hint(r)}")
            if _consec_429[model] >= _MAX_CONSEC_429:
                log.warn(f"gemini[{model}] quota exhausted (repeated 429) — disabling for this run")
                _disabled.add(model)
                return None
            time.sleep(6 * (attempt + 1))
            continue
        if r.status_code in (400, 403, 404):
            # bad key / model / request — don't retry, disable this model for the run
            log.warn(f"gemini[{model}] {r.status_code}: {r.text[:160]} — disabling for this run")
            _disabled.add(model)
            return None
        if r.status_code >= 500:
            log.warn(f"gemini[{model}] server {r.status_code}, retrying")
            continue

        _consec_429[model] = 0
        _calls += 1
        try:
            data = r.json()
            cands = data.get("candidates") or []
            if not cands:
                fb = data.get("promptFeedback", {})
                log.warn(f"gemini[{model}] empty response (block={fb.get('blockReason')})")
                return None
            parts = cands[0].get("content", {}).get("parts") or []
            # 생각 토큰이 섞여 오면 `thought: true` 파트다 — 답에서 뺀다.
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
            if not text and cands[0].get("finishReason") == "MAX_TOKENS":
                log.warn(f"gemini[{model}] hit max tokens before answering")
            return _loads(text) if text else None
        except (ValueError, KeyError) as exc:
            log.warn(f"gemini[{model}] parse failed: {exc}")
            return None

    return None


def _quota_hint(r) -> str:
    """429 응답에서 걸린 쿼터 이름만 뽑는다 (`...PerDay...` 면 일일 한도)."""
    try:
        details = r.json().get("error", {}).get("details", [])
    except ValueError:
        return r.text[:120]
    for d in details:
        for v in d.get("violations", []) or []:
            return f"{v.get('quotaId', '?')} limit={v.get('quotaValue', '?')}"
    return r.text[:120]


def _loads(text: str):
    """Parse JSON, tolerating markdown code fences the model may add."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```", 2)[1] if "```" in s[3:] else s[3:]
        if s.startswith("json"):
            s = s[4:]
    # fall back to the first {...} or [...] span
    for open_c, close_c in (("[", "]"), ("{", "}")):
        i, j = s.find(open_c), s.rfind(close_c)
        if 0 <= i < j:
            try:
                return json.loads(s[i:j + 1])
            except json.JSONDecodeError:
                continue
    return None


# --------------------------------------------------------------------------
# Event cause summaries (R5)
# --------------------------------------------------------------------------
_EXPLAIN_INSTRUCT = (
    "당신은 주식 초보자를 위한 한국어 시장 해설가입니다. 아래 각 급등락 건에 대해, "
    "그날의 뉴스를 근거로 왜 움직였는지 설명하세요.\n"
    "규칙: 2~3문장, 존댓말, 쉬운 말. 전문용어는 그 자리에서 풀어 설명. "
    "뉴스 근거가 약하면 단정하지 말고 '~로 보입니다'로 표현하고 confidence를 low로. "
    "매수/매도 의견·목표가·투자권유 금지.\n"
    'JSON 배열로만 답하세요. 각 원소: {"id": 입력 id 그대로, "headline": 30자 이내 핵심요약, '
    '"explain": 2~3문장 해설, "sentiment": "positive"|"negative"|"neutral", '
    '"confidence": "high"|"medium"|"low", "tags": ["키워드", ...]}'
)


def explain_events(items: list[dict]) -> dict[str, dict]:
    """Summarize a list of events. Respects the global budget; returns id→result.

    ``items``: [{id, name, code, market, date, changePct, volumeRatio, news:[title,...]}]
    """
    global _budget
    if not available(GEMINI_BULK_MODEL) or _budget <= 0 or not items:
        return {}

    allowed = items[:_budget]
    out: dict[str, dict] = {}

    for i in range(0, len(allowed), LLM_EVENT_BATCH):
        batch = allowed[i:i + LLM_EVENT_BATCH]
        blocks = []
        for e in batch:
            news = "\n".join(f"    · {t}" for t in e.get("news", [])[:5]) or "    · (관련 뉴스 없음)"
            dir_ = "상승" if e["changePct"] > 0 else "하락"
            blocks.append(
                f"[id={e['id']}] {e['name']}({e['code']}, {e['market']}) {e['date']}: "
                f"{e['changePct']:+.2f}% {dir_}, 거래량 평소대비 {e.get('volumeRatio') or '?'}배\n"
                f"  관련 뉴스:\n{news}"
            )
        prompt = _EXPLAIN_INSTRUCT + "\n\n입력:\n" + "\n\n".join(blocks)

        data = _post(prompt, model=GEMINI_BULK_MODEL)
        rows = data if isinstance(data, list) else (data.get("items") if isinstance(data, dict) else None)
        if not rows:
            continue
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                out[str(row["id"])] = row
        _budget -= len(batch)
        if _budget <= 0:
            break

    return out


# --------------------------------------------------------------------------
# Brief commentary — headline, 3 points, analysis, news picks (one call)
# --------------------------------------------------------------------------
def brief_analysis(prompt: str) -> dict | None:
    """브리핑 해설을 한 번에 받는다. 프롬프트 조립과 검증은 `build/brief.py` 몫이다.

    한 번의 호출로 끝내는 이유는 쿼터다 — 무료 등급은 모델별 하루 요청 수가 빠듯해서
    3줄·해설·뉴스 선택을 따로 부르면 그만큼 실패할 기회가 늘어난다.
    """
    if not available(GEMINI_MODEL):
        return None
    data = _post(prompt, model=GEMINI_MODEL, max_tokens=GEMINI_BRIEF_MAX_TOKENS,
                 thinking=GEMINI_BRIEF_THINKING, temperature=0.4)
    return data if isinstance(data, dict) else None


# --------------------------------------------------------------------------
# Foreign-news translation
# --------------------------------------------------------------------------
def translate(texts: list[str]) -> list[str]:
    """Translate a list of English strings to Korean. Returns same length;
    on any failure the original string is kept for that slot."""
    if not available(GEMINI_BULK_MODEL) or not texts:
        return list(texts)

    result = list(texts)
    from ..config import TRANSLATE_BATCH
    for i in range(0, len(texts), TRANSLATE_BATCH):
        batch = texts[i:i + TRANSLATE_BATCH]
        numbered = "\n".join(f"{j}. {t}" for j, t in enumerate(batch))
        prompt = (
            "다음 영어 금융 뉴스 문장들을 자연스러운 한국어로 번역하세요. "
            "고유명사·티커는 그대로 두고, 의미를 정확히 옮기세요.\n"
            'JSON 배열로만 답하세요: [{"i": 번호, "ko": "번역"}]\n\n'
            + numbered
        )
        data = _post(prompt, model=GEMINI_BULK_MODEL)
        rows = data if isinstance(data, list) else None
        if not rows:
            continue
        for row in rows:
            if isinstance(row, dict) and "i" in row and row.get("ko"):
                idx = i + int(row["i"])
                if 0 <= idx < len(result):
                    result[idx] = str(row["ko"]).strip()
    return result


def stats() -> str:
    off = f", disabled={sorted(_disabled)}" if _disabled else ""
    return f"gemini calls={_calls}, budget left={_budget}{off}"
