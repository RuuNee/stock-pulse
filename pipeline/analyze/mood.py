"""Market-mood traffic light (schema §2).

A single 0-100 score per market so the home screen can say "오늘 시장 분위기:
중립" before showing any numbers. Deliberately simple and explainable — this is
a beginner cue, not a trading signal.
"""

from __future__ import annotations


def score_market(market: str, indices: list[dict], movers: dict) -> dict:
    parts: list[float] = []

    # 40% — headline index move, mapped so -2%..+2% spans the range.
    idx = _primary_index(market, indices)
    if idx and idx.get("changePct") is not None:
        parts.append(("index", 0.40, _clamp((idx["changePct"] + 2) / 4)))

    # 25% — breadth: share of tracked movers that rose.
    ups = len(movers.get("up", []))
    downs = len(movers.get("down", []))
    if ups + downs:
        parts.append(("breadth", 0.25, ups / (ups + downs)))

    # 15% — VIX inverted (calm = bullish). Only meaningful for US bucket but
    # global fear spills over, so we apply it to both.
    vix = _find(indices, "VIX")
    if vix and vix.get("value") is not None:
        parts.append(("vix", 0.15, _clamp((30 - vix["value"]) / 20)))

    # 10% — USD/KRW inverted for KR (weak won pressures foreign flows).
    if market == "KR":
        fx = _find(indices, "USD/KRW")
        if fx and fx.get("changePct") is not None:
            parts.append(("fx", 0.10, _clamp((1 - fx["changePct"]) / 2)))

    if not parts:
        return {"score": 50, "label": "중립", "color": "amber",
                "reason": "데이터가 부족해 분위기를 판단하기 어렵습니다."}

    weight = sum(w for _, w, _ in parts)
    raw = sum(w * v for _, w, v in parts) / weight
    score = round(raw * 100)

    label, color = _band(score)
    return {
        "score": score,
        "label": label,
        "color": color,
        "reason": _reason(market, idx, ups, downs, vix),
    }


def _band(score: int) -> tuple[str, str]:
    if score >= 65:
        return "양호", "green"
    if score >= 35:
        return "중립", "amber"
    return "위축", "red"


def _reason(market, idx, ups, downs, vix) -> str:
    bits: list[str] = []
    if idx and idx.get("changePct") is not None:
        move = "상승" if idx["changePct"] >= 0 else "하락"
        bits.append(f"{idx['name']}가 {abs(idx['changePct']):.2f}% {move}")
    if ups + downs:
        bits.append(f"주요 종목 중 {ups}개 상승·{downs}개 하락")
    if vix and vix.get("value") is not None:
        state = "안정" if vix["value"] < 20 else "불안"
        bits.append(f"공포지수(VIX) {vix['value']:.0f}선으로 {state}")
    return ", ".join(bits) + "합니다." if bits else "시장이 조용한 편입니다."


def _primary_index(market: str, indices: list[dict]) -> dict | None:
    key = "KS11" if market == "KR" else "US500"
    return _find(indices, key)


def _find(indices: list[dict], key: str) -> dict | None:
    return next((i for i in indices if i["key"] == key), None)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))
