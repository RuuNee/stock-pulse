"""Google Gemini (free tier) client for the pipeline's LLM features.

Three jobs: (1) beginner-friendly cause summaries for chart events, (2) the
brief's 3-line summary, (3) auto-translating foreign (US) news to Korean.

Free-tier quotas are per-minute and per-day, so this module keeps a GLOBAL
per-run budget for event summaries, batches requests, throttles between calls,
and degrades gracefully (returns None → callers fall back to rules) on any
error, quota hit, or missing key. Raw REST via requests — no SDK dependency.
"""

from __future__ import annotations

import json
import time

import requests

from ..config import (
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
_disabled = False    # set True after a hard failure so we stop hammering
_consec_429 = 0      # consecutive rate-limit hits → circuit breaker

_MAX_CONSEC_429 = 3  # after this many, give up on the LLM for the whole run


def available() -> bool:
    return LLM_ENABLED and gemini_key() is not None and not _disabled


def reset() -> None:
    """Call once at the start of a run."""
    global _budget, _calls, _disabled, _consec_429
    _budget = LLM_MAX_EVENTS_PER_RUN
    _calls = 0
    _disabled = False
    _consec_429 = 0


def _post(prompt: str, *, max_tokens: int = GEMINI_MAX_TOKENS, retries: int = 2):
    """One Gemini call. Returns parsed JSON (dict|list) or None."""
    global _calls, _disabled
    key = gemini_key()
    if not key or _disabled:
        return None

    global _consec_429
    url = _ENDPOINT.format(model=GEMINI_MODEL)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": max_tokens,
            "responseMimeType": "application/json",
            # 2.5-flash is a thinking model; disable thinking for fast, clean JSON.
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }

    for attempt in range(retries + 1):
        time.sleep(GEMINI_DELAY_SEC)  # throttle to stay under free-tier RPM
        try:
            r = requests.post(url, params={"key": key}, json=body, timeout=60)
        except Exception as exc:
            log.warn(f"gemini request error: {exc}")
            continue

        if r.status_code == 429:
            _consec_429 += 1
            if _consec_429 >= _MAX_CONSEC_429:
                log.warn("gemini quota exhausted (repeated 429) — disabling LLM for this run")
                _disabled = True
                return None
            wait = 6 * (attempt + 1)
            log.warn(f"gemini rate-limited (429), waiting {wait}s")
            time.sleep(wait)
            continue
        if r.status_code in (400, 403, 404):
            # bad key / model / request — don't retry, disable for the run
            log.warn(f"gemini {r.status_code}: {r.text[:160]} — disabling LLM for this run")
            _disabled = True
            return None
        if r.status_code >= 500:
            log.warn(f"gemini server {r.status_code}, retrying")
            continue

        _consec_429 = 0
        _calls += 1
        try:
            data = r.json()
            cands = data.get("candidates") or []
            if not cands:
                fb = data.get("promptFeedback", {})
                log.warn(f"gemini empty response (block={fb.get('blockReason')})")
                return None
            parts = cands[0].get("content", {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts).strip()
            return _loads(text) if text else None
        except (ValueError, KeyError) as exc:
            log.warn(f"gemini parse failed: {exc}")
            return None

    return None


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
    if not available() or _budget <= 0 or not items:
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

        data = _post(prompt)
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
# Brief 3-line summary
# --------------------------------------------------------------------------
def brief_summary(label: str, snapshot_text: str, headlines: str, mood: str,
                  technical_text: str = "") -> tuple[str, list[str]] | None:
    if not available():
        return None
    tech = f"차트 분석 요약:\n{technical_text}\n\n" if technical_text else ""
    prompt = (
        "당신은 주식 초보자를 위한 한국어 시장 브리핑 작성자입니다. 사실만 전달하고 "
        "투자 권유는 하지 않습니다.\n\n"
        f"{label} 개장 전 브리핑. 시장 분위기: {mood}.\n"
        f"간밤/전일 지표:\n{snapshot_text}\n\n{tech}오늘 주요 뉴스:\n{headlines}\n\n"
        "초보 투자자가 오늘 시장을 이해하도록 headline 1개와 3줄 요약을 만드세요. "
        "각 줄 한 문장, 존댓말, 쉬운 말. 차트 분석 요약이 주어졌다면 한 줄은 그 내용을 "
        "'차트 지표 기준'이라고 밝히며 쓰되, 매수·매도를 권하는 문장으로 바꾸지 마세요.\n"
        'JSON으로만: {"headline": "한 문장", "threeLines": ["...", "...", "..."]}'
    )
    data = _post(prompt)
    if not isinstance(data, dict):
        return None
    lines = [str(x).strip() for x in (data.get("threeLines") or []) if str(x).strip()][:3]
    if not lines:
        return None
    return str(data.get("headline", "")).strip(), lines


# --------------------------------------------------------------------------
# Foreign-news translation
# --------------------------------------------------------------------------
def translate(texts: list[str]) -> list[str]:
    """Translate a list of English strings to Korean. Returns same length;
    on any failure the original string is kept for that slot."""
    if not available() or not texts:
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
        data = _post(prompt)
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
    return f"gemini calls={_calls}, budget left={_budget}"
