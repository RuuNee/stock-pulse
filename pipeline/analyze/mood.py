"""Market-mood traffic light (schema §2) and the brief's pre-open outlook.

Two scores, two questions:

* `score_market` — "how did the last session go?" Shown on the home screen.
* `outlook` — "how is today's session likely to open?" Shown in the brief.

They used to be the same number. The brief went out before the open with a
score built from the *previous* session, so on 2026-10-15 it said "중립 47점"
while the overnight signals that matter most for Korea — the Philadelphia
semiconductor index (-4.3%) and the US-listed Korea ETF EWY (-4.0%) — were
not in the formula at all. KOSPI fell 7.6% that day.

Both stay deliberately simple and explainable — beginner cues, not trading
signals. Each component maps to 0..1 with 0.5 as neutral, and the `reason`
string names the components that actually moved the score.
"""

from __future__ import annotations


def score_market(market: str, indices: list[dict], breadth: dict | None) -> dict:
    """마지막 세션 분위기. `breadth` = {"up": 상승 종목 수, "down": 하락 종목 수}.

    예전에는 `movers`(상위 8·하위 8 목록)를 받아 `len()` 으로 셌다. 두 목록은 항상
    8개씩이라 "8개 상승·8개 하락"이 매일 찍혔고 25% 가중치가 늘 0.5 였다.
    """
    parts: list[tuple[str, float, float]] = []

    # 40% — headline index move, mapped so -2%..+2% spans the range.
    idx = _primary_index(market, indices)
    if idx and idx.get("changePct") is not None:
        parts.append(("index", 0.40, _clamp((idx["changePct"] + 2) / 4)))

    # 25% — breadth: share of tracked stocks that rose.
    ups, downs = _breadth_counts(breadth)
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


def _breadth_counts(breadth: dict | None) -> tuple[int, int]:
    if not breadth:
        return 0, 0
    ups, downs = breadth.get("up"), breadth.get("down")
    # 예전 형식(movers 목록)이 들어오면 세지 않는다 — 그 길이는 상승·하락 수가 아니다.
    if not isinstance(ups, int) or not isinstance(downs, int):
        return 0, 0
    return ups, downs


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
        bits.append(f"추적 종목 {ups + downs}개 중 {ups}개 상승·{downs}개 하락")
    if vix and vix.get("value") is not None:
        state = "안정" if vix["value"] < 20 else "불안"
        bits.append(f"공포지수(VIX) {vix['value']:.0f}선으로 {state}")
    return ", ".join(bits) + "합니다." if bits else "시장이 조용한 편입니다."


# --------------------------------------------------------------------------
# 개장 전 전망 (브리핑 전용)
# --------------------------------------------------------------------------
# (컴포넌트, 가중치). 합이 1 이 아니어도 된다 — 있는 것만으로 다시 나눈다.
_KR_WEIGHTS = {
    "ewy": 0.35,      # 미국 상장 한국 ETF — 코스피 마감 뒤 미국장에서 더 움직인 몫
    "sox": 0.20,      # 필라델피아 반도체 — 삼성전자·SK하이닉스 방향
    "nasdaq": 0.15,
    "vix": 0.10,
    "fx": 0.10,
    "prior": 0.05,    # 직전 코스피 — 추세와 반발이 섞여 있어 작게
}
_US_WEIGHTS = {
    "es": 0.35,       # S&P 500 선물 — 개장 전 실시간
    "nq": 0.20,       # 나스닥 100 선물
    "vix": 0.15,
    "rates": 0.10,    # 미 10년물 금리 변화 (오르면 부담)
    "prior": 0.10,    # 직전 S&P 500
    "breadth": 0.10,  # 직전 세션 상승·하락 종목 비율
}


def outlook(market: str, indices: list[dict], *, futures: dict | None = None,
            breadth: dict | None = None) -> dict:
    """오늘 세션이 어떻게 열릴지 — 개장 전에 쓸 수 있는 신호만으로.

    `futures` = {"ES=F": {"changePct": .., "live": True}, ...} (US 브리핑용, 없어도 됨).
    반환: {score, label, color, kind: "outlook", reason, drivers: [..]}.
    """
    comps = _kr_components(indices) if market == "KR" else _us_components(indices, futures, breadth)
    weights = _KR_WEIGHTS if market == "KR" else _US_WEIGHTS
    usable = [(k, weights[k], v, why) for k, (v, why) in comps.items() if v is not None]

    if not usable:
        return {"score": 50, "label": "중립", "color": "amber", "kind": "outlook",
                "reason": "개장 전 지표가 부족해 방향을 판단하기 어렵습니다.", "drivers": []}

    total = sum(w for _, w, _, _ in usable)
    raw = sum(w * v for _, w, v, _ in usable) / total
    score = round(raw * 100)
    label, color = outlook_band(score)

    # 점수를 가장 많이 끌어당긴 순서로 이유를 댄다 — 중립(0.5)에서 먼 것부터.
    ranked = sorted(usable, key=lambda c: abs(c[2] - 0.5) * c[1], reverse=True)
    drivers = [why for _, _, v, why in ranked if why and abs(v - 0.5) >= 0.08][:3]
    reason = ", ".join(drivers) if drivers else "밤사이 뚜렷한 방향 신호가 없습니다"
    return {"score": score, "label": label, "color": color, "kind": "outlook",
            "reason": reason, "drivers": drivers}


def outlook_band(score: int) -> tuple[str, str]:
    if score >= 65:
        return "강세 기대", "green"
    if score >= 55:
        return "다소 우호", "green"
    if score >= 45:
        return "중립", "amber"
    if score >= 35:
        return "다소 부담", "amber"
    return "약세 우려", "red"


def ewy_gap(indices: list[dict]) -> float | None:
    """코스피 마감 뒤 미국장에서 한국 주식이 더 움직인 몫 (%).

    계산은 `collect/macro.py` `korea_overnight_gap` 이 한다 — 시세 이력이 필요해서다.
    """
    ewy = _find(indices, "EWY")
    gap = (ewy or {}).get("overnightGap")
    return gap if _is_num(gap) else None


def _kr_components(indices: list[dict]) -> dict[str, tuple[float | None, str]]:
    out: dict[str, tuple[float | None, str]] = {}
    gap = ewy_gap(indices)
    if gap is not None:
        out["ewy"] = (_clamp(0.5 + gap / 6), f"밤사이 한국 ETF(EWY) {gap:+.1f}%")
    sox = _pct(indices, "^SOX")
    if sox is not None:
        out["sox"] = (_clamp(0.5 + sox / 8), f"필라델피아 반도체 {sox:+.1f}%")
    nasdaq = _pct(indices, "IXIC")
    if nasdaq is not None:
        out["nasdaq"] = (_clamp(0.5 + nasdaq / 5), f"나스닥 {nasdaq:+.1f}%")
    out["vix"] = _vix_component(indices)
    fx = _pct(indices, "USD/KRW")
    if fx is not None:
        out["fx"] = (_clamp(0.5 - fx / 2), f"원달러 환율 {fx:+.1f}%")
    prior = _pct(indices, "KS11")
    if prior is not None:
        out["prior"] = (_clamp(0.5 + prior / 6), f"직전 코스피 {prior:+.1f}%")
    return out


def _us_components(indices, futures, breadth) -> dict[str, tuple[float | None, str]]:
    out: dict[str, tuple[float | None, str]] = {}
    for key, comp, span, name in (("ES=F", "es", 3, "S&P 500 선물"),
                                  ("NQ=F", "nq", 4, "나스닥 100 선물")):
        f = (futures or {}).get(key) or {}
        if f.get("live") and _is_num(f.get("changePct")):
            pct = f["changePct"]
            out[comp] = (_clamp(0.5 + pct / span), f"{name} {pct:+.1f}%")
    out["vix"] = _vix_component(indices)
    tnx = _find(indices, "^TNX")
    if tnx and _is_num(tnx.get("change")):
        bp = tnx["change"] * 100            # 금리 1%p = 100bp
        out["rates"] = (_clamp(0.5 - bp / 30), f"미 10년물 금리 {bp:+.0f}bp")
    prior = _pct(indices, "US500")
    if prior is not None:
        out["prior"] = (_clamp(0.5 + prior / 4), f"직전 S&P 500 {prior:+.1f}%")
    ups, downs = _breadth_counts(breadth)
    if ups + downs:
        share = ups / (ups + downs)
        out["breadth"] = (share, f"직전 세션 상승 종목 {share * 100:.0f}%")
    return out


def _vix_component(indices) -> tuple[float | None, str]:
    vix = _find(indices, "VIX")
    if not vix or not _is_num(vix.get("value")):
        return None, ""
    level = _clamp((30 - vix["value"]) / 20)
    chg = vix.get("changePct")
    if not _is_num(chg):
        return level, f"VIX {vix['value']:.1f}"
    jump = _clamp(0.5 - chg / 40)              # 하루 +20% 면 0, -20% 면 1
    return (level + jump) / 2, f"공포지수(VIX) {chg:+.0f}%"


def _pct(indices, key) -> float | None:
    i = _find(indices, key)
    v = i.get("changePct") if i else None
    return v if _is_num(v) else None


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and v == v      # NaN 은 v != v


def _primary_index(market: str, indices: list[dict]) -> dict | None:
    key = "KS11" if market == "KR" else "US500"
    return _find(indices, key)


def _find(indices: list[dict], key: str) -> dict | None:
    return next((i for i in indices if i["key"] == key), None)


def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))
