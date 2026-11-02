"""Claude (Anthropic) client — 키가 있으면 브리핑 해설·이벤트 해설·번역을 먼저 맡는다.

`ANTHROPIC_API_KEY` 가 없으면 아무것도 하지 않고(available() False) llm.py 가 지금까지처럼
Gemini → 규칙으로 간다. 실패해도 예외를 밖으로 내지 않고 None 을 돌려준다.

* 응답은 JSON 스키마로 강제한다(`output_config.format`) — Gemini 경로처럼 코드펜스·잡음을
  걷어 낼 필요가 없다. 내용 검증(차트 신호 줄, 없는 후보 번호 등)은 그대로 build/brief.py 몫.
* 거절(refusal)되면 서버가 다른 모델로 한 번 더 돌린다(`fallbacks: "default"`). Haiku 에는
  없는 기능이라 Haiku 로 바꿔 두면 빼고 보낸다. 그래도 거절이면 None → Gemini.
* `temperature` 는 보내지 않는다 — 2026-10-21 부터 모든 모델에서 400 이다.
* 호출마다 토큰과 대략의 금액을 로그에 남긴다 (config.CLAUDE_PRICES).
"""

from __future__ import annotations

import importlib.util
import json

from ..config import CLAUDE_ENABLED, CLAUDE_PRICES, anthropic_key
from ..util import log

_FALLBACK_BETA = "server-side-fallback-2026-07-01"

_client = None
_disabled: set[str] = set()       # 이번 실행에서 죽은 모델. "*" 는 키·결제 문제로 전부
_usage: dict[str, list[int]] = {}  # model -> [calls, input_tokens, output_tokens]


def available(model: str | None = None) -> bool:
    if not (CLAUDE_ENABLED and anthropic_key()) or "*" in _disabled:
        return False
    if model and model in _disabled:
        return False
    return importlib.util.find_spec("anthropic") is not None


def reset() -> None:
    _disabled.clear()
    _usage.clear()


def _get_client():
    global _client
    if _client is None:
        import anthropic
        # SDK 가 429·5xx·연결 오류를 2번 다시 시도한다. 그 뒤에도 실패면 Gemini 로 넘어간다.
        _client = anthropic.Anthropic(api_key=anthropic_key(), max_retries=2, timeout=300.0)
    return _client


def _has_fallback(model: str) -> bool:
    """서버 측 거절 폴백은 Haiku 에 없다 — 대량 모델을 Haiku 로 되돌려도 400 이 안 나게 뺀다."""
    return not model.startswith("claude-haiku")


def ask_json(system: str, user: str, schema: dict, *, model: str, effort: str,
             max_tokens: int, fallback: bool = False):
    """한 번 묻고 스키마에 맞는 JSON(dict)을 돌려준다. 실패하면 None."""
    if not available(model):
        return None
    import anthropic

    params = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
        "output_config": {"effort": effort,
                          "format": {"type": "json_schema", "schema": schema}},
    }
    try:
        if fallback and _has_fallback(model):
            resp = _get_client().beta.messages.create(
                betas=[_FALLBACK_BETA], fallbacks="default", **params)
        else:
            resp = _get_client().messages.create(**params)
    except anthropic.AuthenticationError:
        log.warn("claude: API 키가 거절됨 — 이번 실행은 Claude 를 쓰지 않습니다")
        _disabled.add("*")
        return None
    except anthropic.PermissionDeniedError as exc:
        log.warn(f"claude: 권한 없음 ({_brief(exc)}) — 이번 실행은 Claude 를 쓰지 않습니다")
        _disabled.add("*")
        return None
    except anthropic.NotFoundError as exc:
        log.warn(f"claude[{model}] 모델 없음 ({_brief(exc)}) — 이 모델은 이번 실행에서 뺍니다")
        _disabled.add(model)
        return None
    except anthropic.BadRequestError as exc:
        text = _brief(exc)
        if "credit" in text.lower() or "billing" in text.lower():
            # 잔액 부족은 몇 번을 다시 해도 같다 — 운영자가 결제 화면을 봐야 한다.
            log.warn(f"claude: 크레딧 부족 ({text}) — 콘솔 Billing 을 확인하세요. Gemini 로 넘어갑니다")
            _disabled.add("*")
        else:
            log.warn(f"claude[{model}] 잘못된 요청 ({text}) — 이 모델은 이번 실행에서 뺍니다")
            _disabled.add(model)
        return None
    except anthropic.RateLimitError as exc:
        log.warn(f"claude[{model}] 요청 한도 초과 ({_brief(exc)}) — 이번 호출은 Gemini 로")
        return None
    except anthropic.APIStatusError as exc:
        log.warn(f"claude[{model}] 서버 오류 {exc.status_code} — 이번 호출은 Gemini 로")
        return None
    except anthropic.APIConnectionError as exc:
        log.warn(f"claude[{model}] 연결 실패 ({exc}) — 이번 호출은 Gemini 로")
        return None

    _record(resp)
    if resp.stop_reason == "refusal":
        log.warn(f"claude[{resp.model}] 응답 거절 — 이번 호출은 Gemini 로")
        return None
    if resp.stop_reason == "max_tokens":
        log.warn(f"claude[{resp.model}] 출력 한도({max_tokens})에 걸림 — 이번 호출은 Gemini 로")
        return None
    text = next((b.text for b in resp.content if getattr(b, "type", "") == "text"), "")
    try:
        data = json.loads(text)
    except ValueError:
        log.warn(f"claude[{resp.model}] JSON 파싱 실패")
        return None
    return data if isinstance(data, dict) else None


def _brief(exc) -> str:
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        err = body.get("error") or {}
        if isinstance(err, dict) and err.get("message"):
            return str(err["message"])[:160]
    return str(exc)[:160]


def _record(resp) -> None:
    usage = getattr(resp, "usage", None)
    if usage is None:
        return
    model = getattr(resp, "model", None) or "?"
    tokens_in = (getattr(usage, "input_tokens", 0) or 0) + \
        (getattr(usage, "cache_read_input_tokens", 0) or 0) + \
        (getattr(usage, "cache_creation_input_tokens", 0) or 0)
    tokens_out = getattr(usage, "output_tokens", 0) or 0
    row = _usage.setdefault(model, [0, 0, 0])
    row[0] += 1
    row[1] += tokens_in
    row[2] += tokens_out
    log.info(f"claude[{model}] in={tokens_in:,} out={tokens_out:,} ≈ ${cost(model, tokens_in, tokens_out):.4f}")


def cost(model: str, tokens_in: int, tokens_out: int) -> float:
    price_in, price_out = CLAUDE_PRICES.get(model, (0.0, 0.0))
    return (tokens_in * price_in + tokens_out * price_out) / 1_000_000


def stats() -> str:
    if not _usage:
        return "claude calls=0"
    parts, total = [], 0.0
    for model, (calls, tin, tout) in sorted(_usage.items()):
        c = cost(model, tin, tout)
        total += c
        parts.append(f"{model} ×{calls} ${c:.3f}")
    return f"claude {', '.join(parts)} (합계 ≈ ${total:.3f})"
