"""차트 분석 — 널리 쓰이는 기술적 분석 기법을 한곳에 모은 판정기.

세 가지를 한다.

1. **지표 시계열** (`series`) — 차트에 그대로 겹쳐 그릴 수 있게 OHLCV 행과
   1:1 정렬된 배열을 만든다. 이동평균 4종 · 볼린저밴드 · MACD · RSI.
2. **기법별 판정** (`analyze`) — 마지막 봉 기준으로 기법 12가지를 각각
   강세/약세/중립으로 읽고, 가중 합산해 -100~+100 종합 점수를 낸다.
3. **행동 신호** — "지금 이 차트가 교과서적으로 어떤 국면인가"를 한 줄로
   옮긴다. 추격 매수 · 추가 매수(눌림목) · 분할 차익실현 · 손절 유의 · 관망.

## 왜 규칙 기반인가
전부 과거 가격에서 나오는 결정론적 계산이라 LLM 예산을 전혀 안 쓰고, 같은
입력에 늘 같은 답을 준다. 종목 184개를 매 sync마다 돌려도 비용이 0이다.

## 한계 (UI·브리핑에 반드시 함께 노출한다)
지표는 전부 **과거 가격의 후행 요약**이다. 횡보장에서는 크로스 신호가 계속
어긋나고, 급등 뒤 과매수 판정은 상승장에서 몇 주씩 틀린 채로 남는다. 실적·
공시 같은 재료는 아예 보지 않는다. 그래서 결과물은 "차트가 이렇게 생겼다"는
관찰이지 매매 지시가 아니며, `disclaimer` 필드를 항상 함께 내보낸다.
"""

from __future__ import annotations

import pandas as pd

from ..config import (
    TA_BREAKOUT_LOOKBACK,
    TA_CROSS_LOOKBACK,
    TA_LEVEL_NEAR_PCT,
    TA_LEVEL_RECENT_BARS,
    TA_MIN_BARS,
    TA_PULLBACK_BAND,
    TA_RSI_OVERBOUGHT,
    TA_RSI_OVERSOLD,
    TA_SIGNAL_BANDS,
    TA_TREND_BREAK_GRACE,
    TA_TREND_LOOKBACK,
    TA_TREND_MIN_APART,
    TA_TREND_NEAR_PCT,
    TA_TREND_PIVOT_SPAN,
    TA_TREND_RESPECT_PCT,
    TA_VOLUME_SURGE,
)

DISCLAIMER = (
    "차트 지표만 기계적으로 계산한 결과입니다. 실적·공시 같은 재료는 반영하지 "
    "않으며, 투자 권유가 아닙니다."
)

# 종합 판정 라벨. 점수 구간은 config.TA_SIGNAL_BANDS.
SIGNAL_LABELS: dict[str, str] = {
    "strongBuy": "강한 매수 신호",
    "buy": "매수 우위",
    "neutral": "중립 · 관망",
    "sell": "매도 우위",
    "strongSell": "강한 매도 신호",
}

# 행동 신호: key → (이모지, 라벨, 무엇을 보고 그렇게 읽었는지)
ACTIONS: dict[str, tuple[str, str, str]] = {
    "chase": ("🚀", "추격 매수 신호",
              "상승 추세에서 저항선·신고가를 거래량과 함께 뚫었습니다. 흔히 돌파 추격 구간이라 "
              "부르지만, 돌파가 실패하면 되돌림도 그만큼 빠릅니다."),
    "addBuy": ("➕", "추가 매수(눌림목) 신호",
               "추세는 위를 향하는데 주가가 20일선 근처까지 쉬어 가는 구간입니다. 조정 폭이 "
               "얕을 때 분할로 담는 자리로 해석하는 기법이지만, 20일선을 깨고 내려가면 신호가 사라집니다."),
    "buy": ("📈", "매수 전환 신호",
            "이동평균·MACD 같은 추세 지표가 위쪽으로 방향을 틀었습니다. 추세 전환 초입으로 "
            "읽는 자리이며, 되돌림으로 신호가 무효가 되는 일도 잦습니다."),
    "takeProfit": ("💰", "과열 — 분할 차익실현 구간",
                   "단기 과열 지표가 상단에 몰려 있습니다. 상승이 이어질 수도 있지만, "
                   "비중을 나눠 정리하며 대응하는 구간으로 봅니다."),
    "reduce": ("📉", "비중 축소 신호",
               "추세 지표가 아래를 향합니다. 반등이 나와도 되돌림 매물이 나오기 쉬운 구간으로 읽습니다."),
    "stopLoss": ("🛑", "지지선 이탈 — 손절 유의",
                 "지지선으로 보던 가격대를 아래로 내줬습니다. 이탈이 굳어지면 다음 지지선까지 "
                 "밀리는 경우가 많아, 손실 관리 기준을 정해 두는 자리로 봅니다."),
    "rebound": ("🔍", "낙폭 과대 — 반등 확인 구간",
                "단기 침체 지표가 바닥권입니다. 기술적 반등이 나오기 쉬운 자리지만, "
                "하락 추세 자체가 꺾였는지는 아직 확인되지 않았습니다."),
    "hold": ("👀", "관망 구간",
             "방향을 가리키는 지표가 서로 엇갈립니다. 뚜렷한 신호가 나올 때까지 기다리는 자리입니다."),
}

_DIR = {"bullish": 1, "bearish": -1, "neutral": 0}


# ==========================================================================
# 1. 지표 시계열 — 차트 오버레이용 (ohlcv.rows 와 길이·순서가 같다)
# ==========================================================================
def series(df: pd.DataFrame) -> dict[str, list[float | None]]:
    close, volume = df["Close"], df["Volume"]
    mid, upper, lower = bollinger(close)
    macd_line, macd_sig, macd_hist = macd(close)
    return {
        "ma5": _list(close.rolling(5).mean()),
        "ma20": _list(close.rolling(20).mean()),
        "ma60": _list(close.rolling(60).mean()),
        "ma120": _list(close.rolling(120).mean()),
        "rsi14": _list(rsi(close, 14), 1),
        "volMa20": _list(volume.rolling(20).mean(), 0),
        "bbUpper": _list(upper),
        "bbLower": _list(lower),
        # MACD 는 원화 종목이면 수백, 미국 저가주면 0.0x 라 자릿수를 넉넉히 둔다.
        "macd": _list(macd_line, 3),
        "macdSignal": _list(macd_sig, 3),
        "macdHist": _list(macd_hist, 3),
    }


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    # 0 을 pd.NA 로 바꾸면 series 가 object dtype 이 되어 fillna 가 경고를 뱉는다.
    # float NaN 으로 두면 dtype 이 유지되고 나눗셈 결과도 그대로 NaN 이다.
    rs = gain / loss.replace(0, float("nan"))
    return (100 - 100 / (1 + rs)).fillna(50)


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    line = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    sig = line.ewm(span=signal, adjust=False).mean()
    return line, sig, line - sig


def bollinger(close: pd.Series, period: int = 20, mult: float = 2.0):
    mid = close.rolling(period).mean()
    sd = close.rolling(period).std()
    return mid, mid + mult * sd, mid - mult * sd


def stochastic(high: pd.Series, low: pd.Series, close: pd.Series,
               period: int = 14, smooth_k: int = 3, smooth_d: int = 3):
    lowest, highest = low.rolling(period).min(), high.rolling(period).max()
    # 0 을 pd.NA 로 두면 series 가 object dtype 이 되고 뒤의 rolling().mean() 이
    # "No numeric types to aggregate" 로 죽는다. 14일 내내 같은 값인 얇은 ETF 가
    # 실제로 여기에 걸렸다. float NaN 이면 dtype 이 유지된다.
    span = (highest - lowest).replace(0, float("nan"))
    raw_k = (close - lowest) / span * 100
    k = raw_k.rolling(smooth_k).mean()
    return k, k.rolling(smooth_d).mean()


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([high - low, (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


# ==========================================================================
# 2. 종합 분석
# ==========================================================================
def analyze(df: pd.DataFrame) -> dict | None:
    """마지막 봉 기준 차트 분석 결과. 데이터가 짧으면 None."""
    if df is None or len(df) < TA_MIN_BARS:
        return None

    ctx = _context(df)
    signals = [s for s in (check(ctx) for check in _CHECKS) if s]
    if not signals:
        return None

    score = _composite(signals)
    signal_key = _band(score)
    action_key = _action(ctx, signals, score)
    emoji, action_label, action_note = ACTIONS[action_key]

    return {
        "date": ctx["date"],
        "score": score,
        "signal": signal_key,
        "label": SIGNAL_LABELS[signal_key],
        "action": action_key,
        "actionEmoji": emoji,
        "actionLabel": action_label,
        "actionNote": action_note,
        "headline": _headline(ctx, signals),
        "summary": _summary(ctx, signals, score),
        "trend": ctx["trend"],
        "counts": {
            "bullish": sum(1 for s in signals if s["verdict"] == "bullish"),
            "bearish": sum(1 for s in signals if s["verdict"] == "bearish"),
            "neutral": sum(1 for s in signals if s["verdict"] == "neutral"),
        },
        "signals": signals,
        "levels": ctx["levels"],
        "trendlines": ctx["trendlines"],
        "risk": ctx["risk"],
        "disclaimer": DISCLAIMER,
    }


def _context(df: pd.DataFrame) -> dict:
    """판정기들이 공유하는 계산 결과. 지표를 한 번만 돌리려고 모아 둔다."""
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
    ma = {n: close.rolling(n).mean() for n in (5, 20, 60, 120)}
    bb_mid, bb_up, bb_low = bollinger(close)
    macd_line, macd_sig, macd_hist = macd(close)
    k, d = stochastic(high, low, close)
    rsi14 = rsi(close, 14)
    atr14 = atr(high, low, close, 14)

    price = float(close.iloc[-1])
    ctx: dict = {
        "date": df.index[-1].strftime("%Y-%m-%d"),
        "close": close, "high": high, "low": low, "vol": vol,
        "price": price,
        "ma": {n: _last(s) for n, s in ma.items()},
        "maSeries": ma,
        "bb": (_last(bb_mid), _last(bb_up), _last(bb_low)),
        "macd": (_last(macd_line), _last(macd_sig), _last(macd_hist)),
        "macdHistPrev": _at(macd_hist, -2),
        "macdSeries": (macd_line, macd_sig),
        "rsi": _last(rsi14),
        "rsiPrev": _at(rsi14, -2),
        "stoch": (_last(k), _last(d)),
        "stochPrev": (_at(k, -2), _at(d, -2)),
        "atr": _last(atr14),
    }

    ctx["trend"] = _trend_block(ctx)
    ctx["levels"] = _levels(df, price)
    ctx["trendlines"] = _trendlines(df, price)
    ctx["risk"] = _risk(ctx)
    return ctx


def _trend_block(ctx: dict) -> dict:
    """정배열/역배열과 60일선 기울기로 큰 그림 한 줄."""
    price, ma = ctx["price"], ctx["ma"]
    ma5, ma20, ma60 = ma.get(5), ma.get(20), ma.get(60)
    slope = _slope_pct(ctx["maSeries"][60], 20)

    if _all(ma5, ma20, ma60) and ma5 > ma20 > ma60:
        phase, direction = "정배열", "up"
    elif _all(ma5, ma20, ma60) and ma5 < ma20 < ma60:
        phase, direction = "역배열", "down"
    elif ma60 is not None and price > ma60:
        phase, direction = "혼조(중기선 위)", "up"
    elif ma60 is not None and price < ma60:
        phase, direction = "혼조(중기선 아래)", "down"
    else:
        phase, direction = "혼조", "flat"

    if slope is not None and abs(slope) < 1.0:
        strength = "횡보"
    elif slope is not None and slope > 0:
        strength = "상승"
    elif slope is not None:
        strength = "하락"
    else:
        strength = "판단보류"

    label = {"횡보": f"{phase} · 중기 횡보", "판단보류": phase}.get(
        strength, f"{phase} · 중기 {strength}추세")
    return {
        "phase": phase,
        "direction": direction,
        "slopePct": slope,
        "label": label,
        "aboveMa60": None if ma60 is None else price > ma60,
    }


def _levels(df: pd.DataFrame, price: float) -> dict:
    """지지·저항 — 현재가에서 **가장 가까운** 기준선.

    후보는 두 종류다.

    1. 스윙 피벗 — 앞뒤 5봉보다 낮은(높은) 골짜기·봉우리. 여러 번 되돌려진
       가격대라 교과서가 말하는 지지·저항에 가장 가깝다.
    2. 최근 20봉의 고·저 — 피벗만 쓰면 한 방향으로만 흐른 구간에서 아무것도
       안 잡힌다. 상승장에서는 정의상 골짜기가 거의 생기지 않기 때문이다.
       실제로 SK하이닉스가 800k→3.2M 상승 후 조정 중일 때, 지지선이 넉 달 전
       808,000(현재가 -42%)으로 찍혔다 — 아무도 참고하지 않을 거리다.

    후보가 한쪽에 하나도 없으면 `None`. 신저가 종목의 "지지선"처럼 실제로
    존재하지 않는 값을 억지로 만들어 내지 않는다.
    """
    window = df.tail(TA_BREAKOUT_LOOKBACK * 2)
    highs, lows = window["High"], window["Low"]

    above = [float(v) for i, v in enumerate(highs)
             if _is_pivot(highs, i, high=True) and float(v) > price]
    below = [float(v) for i, v in enumerate(lows)
             if _is_pivot(lows, i, high=False) and float(v) < price]

    recent = df.tail(TA_LEVEL_RECENT_BARS)
    recent_high, recent_low = _f(recent["High"].max()), _f(recent["Low"].min())
    if recent_high is not None and recent_high > price:
        above.append(recent_high)
    if recent_low is not None and recent_low < price:
        below.append(recent_low)

    resistance = min(above) if above else None   # 위쪽에서 가장 가까운 벽
    support = max(below) if below else None      # 아래쪽에서 가장 가까운 바닥

    return {
        "support": _round(support),
        "resistance": _round(resistance),
        "supportGapPct": _round(_pct(support, price), 2),
        "resistanceGapPct": _round(_pct(resistance, price), 2),
        **_range52(df, price),
    }


def _range52(df: pd.DataFrame, price: float) -> dict:
    """52주 고·저 대비 현재가의 자리.

    세 숫자를 같이 낸다. 셋 다 같은 재료(고점·저점·현재가)에서 나오지만
    답하는 질문이 다르다.

      high52Pct  전고점에서 얼마나 빠졌나  — "회복까지 얼마"
      low52Pct   전저점에서 얼마나 올랐나  — "바닥에서 얼마나 왔나"
      rangePos   저점~고점 구간의 몇 % 지점 — "위쪽인가 아래쪽인가" 한 눈에

    고점과 저점이 같으면(상장 직후 등) `rangePos` 는 `None`. 0 으로 나누지
    않으려는 것도 있지만, 그 상태에서 "0% 지점"은 틀린 말이다.
    """
    high52 = _f(df["High"].tail(252).max())
    low52 = _f(df["Low"].tail(252).min())
    span = (high52 - low52) if _all(high52, low52) else None
    return {
        "high52": _round(high52),
        "low52": _round(low52),
        "high52Pct": _round(_pct(price, high52), 2),
        "low52Pct": _round(_pct(price, low52), 2),
        "rangePos": _round((price - low52) / span * 100, 1) if span else None,
    }


def _is_pivot(s: pd.Series, i: int, *, high: bool, span: int = 5) -> bool:
    if i < span or i >= len(s) - span:
        return False
    window = s.iloc[i - span:i + span + 1]
    return float(s.iloc[i]) == (float(window.max()) if high else float(window.min()))


def _pivots(s: pd.Series, *, high: bool) -> list[tuple[int, float]]:
    """스윙 점 목록 — (위치, 값). 오래된 것부터."""
    span = TA_TREND_PIVOT_SPAN
    return [(i, float(s.iloc[i])) for i in range(len(s))
            if _is_pivot(s, i, high=high, span=span)]


def _trendlines(df: pd.DataFrame, price: float) -> dict:
    """대각 추세선 — 스윙 고점 2개(하락)/저점 2개(상승)를 이은 선.

    수평 지지·저항(`_levels`)이 "얼마"를 본다면 이쪽은 **기울기**를 본다.
    교과서가 그리는 방식 그대로다:

      - 상승추세선 = 점점 높아지는 저점 두 개를 잇는다 (지지 역할)
      - 하락추세선 = 점점 낮아지는 고점 두 개를 잇는다 (저항 역할)

    조건이 안 맞으면 `None` 을 낸다. 저점이 낮아지고 있는데 억지로 이으면
    그건 상승추세선이 아니라 그냥 두 점을 지나는 직선이고, 사람이 차트에
    그어 보는 선과 달라서 오히려 판단을 흐린다. `_levels` 와 같은 원칙이다.

    선은 **마지막 봉까지 연장**해서 오늘 값(`now`)을 낸다. 추세선이 유용한
    건 "오늘 이 가격에서 만난다"이지 과거 두 점이 아니다.
    """
    window = df.tail(TA_TREND_LOOKBACK)
    if len(window) < TA_TREND_MIN_APART * 2:
        return {"up": None, "down": None}

    dates = [ts.strftime("%Y-%m-%d") for ts in window.index]
    last = len(window) - 1

    closes = window["Close"].to_numpy(dtype=float)

    def line(points: list[tuple[int, float]], rising: bool) -> dict | None:
        # 최근 두 점부터 거슬러 올라가며 "방향이 맞는" 짝을 찾는다.
        for a in range(len(points) - 1, 0, -1):
            i2, v2 = points[a]
            for b in range(a - 1, -1, -1):
                i1, v1 = points[b]
                span = i2 - i1
                if span < TA_TREND_MIN_APART:
                    continue
                if (v2 > v1) is not rising:
                    continue

                # 그은 구간보다 더 멀리 연장하지 않는다. 두 점 사이가 20봉인
                # 선을 100봉 뒤까지 늘이면 기울기 오차가 그대로 100배가 된다 —
                # 실제로 삼성전자의 2~3월 고점 두 개가 8월까지 연장돼 현재가
                # 대비 -58% 인 "저항선"으로 나왔다.
                if last - i2 > max(span, TA_TREND_MIN_APART):
                    continue

                slope = (v2 - v1) / span
                now = v2 + slope * (last - i2)
                if now <= 0:      # 연장선이 0 아래로 내려가면 의미 없는 값이다
                    continue

                # 선이 살아 있는지 본다. "뚫렸다"를 한 덩어리로 세면 안 된다 —
                # 방금 깬 것(=우리가 알리고 싶은 신호)과 몇 달 전에 죽은 선이
                # 같은 값으로 나오기 때문이다. 그래서 둘로 나눈다.
                violated = [
                    (closes[j] < lvl) if rising else (closes[j] > lvl)
                    for j in range(i2 + 1, last + 1)
                    if (lvl := v2 + slope * (j - i2)) > 0
                ]

                # ① 끝에서부터 이어진 위반 = 방금 이탈. 유예 안이면 살려 둔다.
                run = 0
                for flag in reversed(violated):
                    if not flag:
                        break
                    run += 1
                if run > TA_TREND_BREAK_GRACE:
                    continue    # 깨고 나서 계속 반대편 — 죽은 선

                # ② 그 앞 구간에서 자주 뚫렸으면 애초에 지켜진 적 없는 선이다.
                #    봉이 몇 개 안 될 때는 판정하지 않는다 — 3봉 중 1봉이면
                #    33% 지만 그걸로 선의 유효성을 말할 수는 없다.
                middle = violated[:len(violated) - run]
                if (len(middle) >= TA_TREND_MIN_APART
                        and sum(middle) / len(middle) > TA_TREND_RESPECT_PCT):
                    continue

                return {
                    "from": {"date": dates[i1], "price": _round(v1)},
                    "to": {"date": dates[i2], "price": _round(v2)},
                    "now": _round(now),
                    "slopePerDay": _round(slope, 4),
                    "gapPct": _round(_pct(price, now), 2),
                }
        return None

    return {
        "up": line(_pivots(window["Low"], high=False), rising=True),
        "down": line(_pivots(window["High"], high=True), rising=False),
    }


def _risk(ctx: dict) -> dict:
    """ATR 로 본 하루 변동폭. '이 종목은 원래 얼마나 흔들리나'."""
    atr_val, price = ctx["atr"], ctx["price"]
    pct = _round(atr_val / price * 100, 2) if atr_val and price else None
    if pct is None:
        band = "판단보류"
    elif pct >= 4.0:
        band = "매우 높음"
    elif pct >= 2.5:
        band = "높음"
    elif pct >= 1.2:
        band = "보통"
    else:
        band = "낮음"
    return {"atrPct": pct, "band": band}


# ==========================================================================
# 기법별 판정 — 각각 dict 하나 또는 None
# ==========================================================================
def _sig(key, name, group, verdict, strength, weight, value, detail) -> dict:
    return {
        "key": key, "name": name, "group": group,
        "verdict": verdict, "strength": round(min(1.0, max(0.0, strength)), 2),
        "weight": weight, "value": value, "detail": detail,
    }


def _c_alignment(ctx: dict) -> dict | None:
    """① 이동평균 배열 — 5·20·60일선이 어떤 순서로 놓였나."""
    ma5, ma20, ma60 = (ctx["ma"].get(n) for n in (5, 20, 60))
    if not _all(ma5, ma20, ma60):
        return None
    if ma5 > ma20 > ma60:
        return _sig("maAlign", "이동평균 정배열", "추세", "bullish", 1.0, 3, "5 > 20 > 60일선",
                    "단기선이 장기선 위에 차례로 놓인 정배열입니다. 교과서적으로 가장 안정적인 "
                    "상승 추세 형태로 봅니다.")
    if ma5 < ma20 < ma60:
        return _sig("maAlign", "이동평균 역배열", "추세", "bearish", 1.0, 3, "5 < 20 < 60일선",
                    "단기선이 장기선 아래에 차례로 놓인 역배열입니다. 하락 추세가 자리 잡은 "
                    "형태로 읽습니다.")
    return _sig("maAlign", "이동평균 배열", "추세", "neutral", 0.0, 3, "뒤섞임",
                "이동평균선들이 뒤엉켜 있습니다. 방향을 정하지 못한 구간입니다.")


def _c_cross(ctx: dict) -> dict | None:
    """② 골든크로스 / 데드크로스 — 20일선이 60일선을 뚫었나."""
    fast, slow = ctx["maSeries"][20], ctx["maSeries"][60]
    diff = (fast - slow).dropna()
    if len(diff) < TA_CROSS_LOOKBACK + 2:
        return None

    recent = diff.tail(TA_CROSS_LOOKBACK + 1)
    ago = None
    for back in range(1, len(recent)):
        now_v, prev_v = float(recent.iloc[-back]), float(recent.iloc[-back - 1])
        if now_v > 0 >= prev_v or now_v <= 0 < prev_v:
            ago = back - 1
            break

    above = float(diff.iloc[-1]) > 0
    if ago is None:
        state = "20일선 > 60일선" if above else "20일선 < 60일선"
        return _sig("maCross", "골든/데드크로스", "추세",
                    "bullish" if above else "bearish", 0.35, 2, state,
                    f"최근 {TA_CROSS_LOOKBACK}거래일 안에 교차는 없었고, {state} 상태가 이어집니다.")

    when = "오늘" if ago == 0 else f"{ago}거래일 전"
    if above:
        return _sig("maCross", "골든크로스 발생", "추세", "bullish", 1.0, 3, f"{when}",
                    f"{when} 20일선이 60일선을 아래에서 위로 뚫었습니다(골든크로스). 상승 추세 "
                    "전환 신호로 보지만, 이미 오른 뒤에 나오는 후행 신호라는 점은 감안해야 합니다.")
    return _sig("maCross", "데드크로스 발생", "추세", "bearish", 1.0, 3, f"{when}",
                f"{when} 20일선이 60일선을 위에서 아래로 뚫었습니다(데드크로스). 하락 추세 "
                "전환 신호로 읽습니다.")


def _c_disparity(ctx: dict) -> dict | None:
    """③ 이격도 — 주가가 20일선에서 얼마나 떨어져 있나."""
    ma20 = ctx["ma"].get(20)
    gap = _pct(ctx["price"], ma20)
    if gap is None:
        return None
    value = f"20일선 대비 {gap:+.1f}%"
    if gap >= 12:
        return _sig("disparity", "20일선 이격 과대", "가격대", "bearish", min(1.0, gap / 20), 2, value,
                    f"주가가 20일 평균보다 {gap:.1f}% 위에 있습니다. 너무 벌어지면 평균으로 "
                    "되돌아오려는 힘이 커진다고 봅니다.")
    if gap <= -12:
        return _sig("disparity", "20일선 이격 과소", "가격대", "bullish", min(1.0, -gap / 20), 2, value,
                    f"주가가 20일 평균보다 {abs(gap):.1f}% 아래에 있습니다. 단기 낙폭이 과하다고 "
                    "보는 자리입니다.")
    if abs(gap) <= TA_PULLBACK_BAND:
        return _sig("disparity", "20일선 부근", "가격대", "neutral", 0.0, 2, value,
                    "주가가 20일 평균선에 붙어 있습니다. 추세가 살아 있으면 눌림목, 무너지면 "
                    "이탈로 갈리는 갈림길입니다.")
    return _sig("disparity", "20일선 이격", "가격대",
                "bullish" if gap > 0 else "bearish", min(1.0, abs(gap) / 12), 1, value,
                f"주가가 20일 평균선보다 {abs(gap):.1f}% {'위' if gap > 0 else '아래'}에 있습니다.")


def _c_slope(ctx: dict) -> dict | None:
    """④ 중기 추세 방향 — 60일선이 오르고 있나 내리고 있나."""
    slope = ctx["trend"]["slopePct"]
    if slope is None:
        return None
    value = f"60일선 20일간 {slope:+.1f}%"
    if slope >= 1.0:
        return _sig("trendSlope", "중기 상승추세", "추세", "bullish", min(1.0, slope / 8), 3, value,
                    f"60일 이동평균선이 최근 20거래일 동안 {slope:.1f}% 올랐습니다. 중기 방향이 "
                    "위를 향합니다.")
    if slope <= -1.0:
        return _sig("trendSlope", "중기 하락추세", "추세", "bearish", min(1.0, -slope / 8), 3, value,
                    f"60일 이동평균선이 최근 20거래일 동안 {abs(slope):.1f}% 내렸습니다. 중기 방향이 "
                    "아래를 향합니다.")
    return _sig("trendSlope", "중기 횡보", "추세", "neutral", 0.0, 3, value,
                "60일선이 거의 눕혀져 있습니다. 방향성 없는 박스권으로 봅니다.")


def _c_macd(ctx: dict) -> dict | None:
    """⑤ MACD — 단기·장기 평균의 차이로 보는 모멘텀."""
    line, sig, hist = ctx["macd"]
    if not _all(line, sig, hist):
        return None
    prev = ctx["macdHistPrev"]
    crossed_up = prev is not None and prev <= 0 < hist
    crossed_down = prev is not None and prev >= 0 > hist
    # 원화 종목은 히스토그램이 네 자릿수까지 간다 — 자릿수 구분 없이 찍으면
    # "-5398.25" 처럼 읽히지 않는다. 반대로 미국 저가주는 0.0x 라 소수점이 필요하다.
    value = (f"히스토그램 {hist:+,.0f}" if abs(hist) >= 100
             else f"히스토그램 {hist:+.2f}")

    if crossed_up:
        return _sig("macd", "MACD 상향 교차", "모멘텀", "bullish", 1.0, 3, value,
                    "MACD가 시그널선을 위로 뚫었습니다. 상승 쪽으로 힘이 실리기 시작했다고 보는 신호입니다.")
    if crossed_down:
        return _sig("macd", "MACD 하향 교차", "모멘텀", "bearish", 1.0, 3, value,
                    "MACD가 시그널선을 아래로 뚫었습니다. 상승 힘이 꺾였다고 보는 신호입니다.")
    if hist > 0:
        growing = prev is not None and hist > prev
        return _sig("macd", "MACD 시그널 위", "모멘텀", "bullish", 0.6 if growing else 0.4, 2, value,
                    "MACD가 시그널선 위에 있습니다. 상승 힘이 "
                    + ("더 붙는 중입니다." if growing else "유지되지만 줄고 있습니다."))
    shrinking = prev is not None and hist > prev
    return _sig("macd", "MACD 시그널 아래", "모멘텀", "bearish", 0.4 if shrinking else 0.6, 2, value,
                "MACD가 시그널선 아래에 있습니다. 하락 힘이 "
                + ("약해지는 중입니다." if shrinking else "이어지고 있습니다."))


def _c_rsi(ctx: dict) -> dict | None:
    """⑥ RSI — 최근 상승분과 하락분의 비율로 보는 과열/침체."""
    val, prev = ctx["rsi"], ctx["rsiPrev"]
    if val is None:
        return None
    value = f"RSI {val:.0f}"
    if val >= TA_RSI_OVERBOUGHT:
        return _sig("rsi", "RSI 과매수", "모멘텀", "bearish",
                    min(1.0, (val - TA_RSI_OVERBOUGHT) / 15 + 0.4), 2, value,
                    f"RSI가 {val:.0f}으로 과매수 기준({TA_RSI_OVERBOUGHT:.0f})을 넘었습니다. "
                    "다만 강한 상승장에서는 과매수 상태로도 한참 더 오르기도 합니다.")
    if val <= TA_RSI_OVERSOLD:
        return _sig("rsi", "RSI 과매도", "모멘텀", "bullish",
                    min(1.0, (TA_RSI_OVERSOLD - val) / 15 + 0.4), 2, value,
                    f"RSI가 {val:.0f}으로 과매도 기준({TA_RSI_OVERSOLD:.0f}) 아래입니다. "
                    "단기 반등이 나오기 쉬운 자리로 보지만, 하락 추세에서는 낮은 값이 오래 갑니다.")
    if prev is not None and prev < 50 <= val:
        return _sig("rsi", "RSI 50선 회복", "모멘텀", "bullish", 0.6, 2, value,
                    "RSI가 중립선인 50을 위로 넘었습니다. 매수세가 매도세보다 우위로 돌아섰다는 뜻입니다.")
    if prev is not None and prev >= 50 > val:
        return _sig("rsi", "RSI 50선 이탈", "모멘텀", "bearish", 0.6, 2, value,
                    "RSI가 중립선인 50을 아래로 내려왔습니다. 매도세가 우위로 돌아섰다는 뜻입니다.")
    return _sig("rsi", "RSI 중립권", "모멘텀",
                "bullish" if val > 55 else "bearish" if val < 45 else "neutral",
                0.3, 1, value, f"RSI {val:.0f} — 과열도 침체도 아닌 구간입니다.")


def _c_bollinger(ctx: dict) -> dict | None:
    """⑦ 볼린저밴드 — 20일 평균 ±2σ 통로에서 주가가 어디쯤인가."""
    mid, up, low = ctx["bb"]
    price = ctx["price"]
    if not _all(mid, up, low) or up <= low:
        return None
    pct_b = (price - low) / (up - low) * 100
    width = (up - low) / mid * 100 if mid else None
    value = f"%B {pct_b:.0f} · 폭 {width:.1f}%" if width is not None else f"%B {pct_b:.0f}"

    if pct_b >= 100:
        return _sig("bollinger", "밴드 상단 돌파", "변동성", "bearish", 0.5, 2, value,
                    "주가가 볼린저밴드 위쪽 선을 뚫고 올라갔습니다. 강한 상승이라는 뜻이지만 "
                    "동시에 단기 과열 구간이기도 해서, 밴드 안으로 되돌아올 때가 많습니다.")
    if pct_b <= 0:
        return _sig("bollinger", "밴드 하단 이탈", "변동성", "bullish", 0.5, 2, value,
                    "주가가 볼린저밴드 아래쪽 선을 뚫고 내려갔습니다. 과매도 구간으로 보지만, "
                    "하락이 이어지면 밴드가 함께 내려가며 이탈이 길어지기도 합니다.")
    if width is not None and width <= 8:
        return _sig("bollinger", "밴드 수축(스퀴즈)", "변동성", "neutral", 0.0, 2, value,
                    f"밴드 폭이 {width:.1f}%까지 좁아졌습니다. 변동성이 눌린 뒤에는 한쪽으로 "
                    "크게 움직이는 경우가 많아, 방향이 나올 때를 기다리는 구간으로 봅니다.")
    if pct_b >= 80:
        return _sig("bollinger", "밴드 상단권", "변동성", "bullish", 0.4, 2, value,
                    "주가가 밴드 위쪽에 붙어 움직입니다. 상승 흐름이 강하다는 신호입니다.")
    if pct_b <= 20:
        return _sig("bollinger", "밴드 하단권", "변동성", "bearish", 0.4, 2, value,
                    "주가가 밴드 아래쪽에 붙어 움직입니다. 하락 압력이 크다는 신호입니다.")
    return _sig("bollinger", "밴드 중앙권", "변동성", "neutral", 0.0, 2, value,
                "주가가 밴드 한가운데를 지나고 있습니다. 방향을 가리지 않는 구간입니다.")


def _c_stochastic(ctx: dict) -> dict | None:
    """⑧ 스토캐스틱 — 최근 고·저 범위에서 종가가 어디에 찍혔나."""
    k, d = ctx["stoch"]
    pk, pd_ = ctx["stochPrev"]
    if not _all(k, d):
        return None
    value = f"%K {k:.0f} / %D {d:.0f}"
    crossed_up = _all(pk, pd_) and pk <= pd_ and k > d
    crossed_down = _all(pk, pd_) and pk >= pd_ and k < d

    if crossed_up and k <= 30:
        return _sig("stochastic", "스토캐스틱 바닥권 골든크로스", "모멘텀", "bullish", 1.0, 2, value,
                    "침체 구간에서 %K가 %D를 위로 뚫었습니다. 단기 반등 시작 신호로 보는 자리입니다.")
    if crossed_down and k >= 70:
        return _sig("stochastic", "스토캐스틱 천장권 데드크로스", "모멘텀", "bearish", 1.0, 2, value,
                    "과열 구간에서 %K가 %D를 아래로 뚫었습니다. 단기 조정 신호로 보는 자리입니다.")
    if k >= 80:
        return _sig("stochastic", "스토캐스틱 과열", "모멘텀", "bearish", 0.5, 1, value,
                    "최근 변동 범위의 위쪽 끝에서 종가가 형성되고 있습니다. 단기 과열 구간입니다.")
    if k <= 20:
        return _sig("stochastic", "스토캐스틱 침체", "모멘텀", "bullish", 0.5, 1, value,
                    "최근 변동 범위의 아래쪽 끝에서 종가가 형성되고 있습니다. 단기 침체 구간입니다.")
    return _sig("stochastic", "스토캐스틱 중립", "모멘텀",
                "bullish" if k > d else "bearish", 0.25, 1, value,
                f"%K가 %D {'위' if k > d else '아래'}에 있습니다. 단기 방향만 가볍게 참고하는 값입니다.")


def _c_volume(ctx: dict) -> dict | None:
    """⑨ 거래량 — 20일 평균 대비 오늘 손바뀜, 그리고 가격과 같은 방향인가."""
    vol = ctx["vol"]
    ma20 = float(vol.tail(20).mean() or 0)
    today = float(vol.iloc[-1] or 0)
    if ma20 <= 0 or today <= 0:
        return None  # 지수·환율처럼 거래량이 없는 계열
    ratio = today / ma20
    close = ctx["close"]
    up_day = float(close.iloc[-1]) >= float(close.iloc[-2])
    value = f"평소의 {ratio:.1f}배"

    if ratio >= TA_VOLUME_SURGE and up_day:
        return _sig("volume", "상승 + 거래량 급증", "수급", "bullish", min(1.0, ratio / 3), 2, value,
                    f"오르면서 거래량이 평소의 {ratio:.1f}배로 늘었습니다. 매수세가 실제로 붙었다는 "
                    "뜻으로, 상승에 힘이 실린 형태로 봅니다.")
    if ratio >= TA_VOLUME_SURGE and not up_day:
        return _sig("volume", "하락 + 거래량 급증", "수급", "bearish", min(1.0, ratio / 3), 2, value,
                    f"내리면서 거래량이 평소의 {ratio:.1f}배로 늘었습니다. 파는 쪽에 힘이 실린 "
                    "형태로 봅니다.")
    if ratio <= 0.6:
        return _sig("volume", "거래량 위축", "수급", "neutral", 0.0, 1, value,
                    "거래가 평소보다 한산합니다. 관심이 식어 방향이 잘 나지 않는 구간입니다.")
    return _sig("volume", "거래량 보통", "수급", "neutral", 0.0, 1, value,
                "거래량이 평소 수준입니다. 특별히 읽을 신호는 없습니다.")


def _c_breakout(ctx: dict) -> dict | None:
    """⑩ 신고가/신저가 돌파 — 이른바 '추격' 판단의 근거."""
    high, low, close = ctx["high"], ctx["low"], ctx["close"]
    n = TA_BREAKOUT_LOOKBACK
    if len(close) < n + 2:
        return None
    prior_high = _f(high.iloc[-n - 1:-1].max())
    prior_low = _f(low.iloc[-n - 1:-1].min())
    price = ctx["price"]
    if not _all(prior_high, prior_low):
        return None

    if price > prior_high:
        over = _pct(price, prior_high) or 0
        return _sig("breakout", f"{n}일 신고가 돌파", "가격대", "bullish", min(1.0, 0.6 + over / 10), 3,
                    f"직전 고점 대비 {over:+.1f}%",
                    f"최근 {n}거래일 최고가를 넘어섰습니다. 위쪽에 매물벽이 없는 자리라 흐름이 "
                    "이어지기 쉽다고 보지만, 되밀리면 돌파 실패로 판단이 뒤집힙니다.")
    if price < prior_low:
        under = _pct(price, prior_low) or 0
        return _sig("breakout", f"{n}일 신저가 이탈", "가격대", "bearish", min(1.0, 0.6 + abs(under) / 10), 3,
                    f"직전 저점 대비 {under:+.1f}%",
                    f"최근 {n}거래일 최저가를 밑돌았습니다. 아래쪽에 받쳐 줄 가격대가 없어 낙폭이 "
                    "커지기 쉬운 구간으로 봅니다.")
    room = _pct(prior_high, price)
    return _sig("breakout", f"{n}일 박스권", "가격대", "neutral", 0.0, 2,
                f"고점까지 {room:+.1f}%" if room is not None else "-",
                f"최근 {n}거래일 고점과 저점 사이에서 움직이고 있습니다. 어느 쪽을 뚫는지가 "
                "다음 방향을 가릅니다.")


def _c_levels(ctx: dict) -> dict | None:
    """⑪ 지지·저항 근접도 — 스윙 고점/저점까지 남은 거리."""
    lv = ctx["levels"]
    up_gap, down_gap = lv.get("resistanceGapPct"), lv.get("supportGapPct")
    if up_gap is None and down_gap is None:
        return None
    value = f"지지 {down_gap:+.1f}% · 저항 {up_gap:+.1f}%" if _all(up_gap, down_gap) else "-"

    if down_gap is not None and abs(down_gap) <= TA_LEVEL_NEAR_PCT:
        return _sig("levels", "지지선 근접", "가격대", "bullish", 0.5, 2, value,
                    f"최근 저점이 만든 지지선({_fmt_num(lv['support'])})에 {abs(down_gap):.1f}% 거리까지 "
                    "내려왔습니다. 여기서 버티면 반등, 깨면 추가 하락으로 보는 자리입니다.")
    if up_gap is not None and abs(up_gap) <= TA_LEVEL_NEAR_PCT:
        return _sig("levels", "저항선 근접", "가격대", "bearish", 0.5, 2, value,
                    f"최근 고점이 만든 저항선({_fmt_num(lv['resistance'])}) 바로 아래입니다. 뚫으면 "
                    "탄력이 붙지만, 막히면 되돌림이 나오는 자리입니다.")
    return _sig("levels", "지지·저항 중간", "가격대", "neutral", 0.0, 1, value,
                "지지선과 저항선 사이에 있습니다. 어느 쪽도 임박하지 않았습니다.")


def _c_trendline(ctx: dict) -> dict | None:
    """⑫ 추세선 — 대각선을 딛고 있나, 눌리고 있나.

    수평 지지·저항(⑪)과 겹쳐 보이지만 다른 것을 잡는다. 저점을 계속 높이며
    오르던 종목이 그 선을 깨는 순간은 가격이 아직 어떤 수평 지지선에도 닿기
    전이다 — 추세선이 먼저 알려 주는 게 그 지점이다.

    돌파·이탈을 근접보다 세게 본다. 추세선은 "닿았다"보다 "깨졌다"가 훨씬
    분명한 신호다.
    """
    lines, price = ctx["trendlines"], ctx["price"]
    up, down = lines.get("up"), lines.get("down")
    near = TA_TREND_NEAR_PCT

    # 상승추세선 이탈 — 저점을 높여 오던 흐름이 끊겼다.
    if up and up["gapPct"] is not None and up["gapPct"] < 0:
        return _sig("trendline", "상승추세선 이탈", "가격대", "bearish",
                    min(1.0, 0.6 + abs(up["gapPct"]) / 10), 3,
                    f"추세선 {up['now']:,.0f} 대비 {up['gapPct']:+.1f}%",
                    "저점을 차례로 높여 오던 선을 아래로 깼습니다. 상승 추세의 전제가 "
                    "무너진 자리로 보며, 되돌아 올라서지 못하면 추세가 바뀐 것으로 읽습니다.")

    # 하락추세선 돌파 — 고점을 낮춰 오던 흐름을 뚫었다.
    if down and down["gapPct"] is not None and down["gapPct"] > 0:
        return _sig("trendline", "하락추세선 돌파", "가격대", "bullish",
                    min(1.0, 0.6 + down["gapPct"] / 10), 3,
                    f"추세선 {down['now']:,.0f} 대비 {down['gapPct']:+.1f}%",
                    "고점을 차례로 낮춰 오던 선을 위로 뚫었습니다. 하락 추세가 꺾이는 "
                    "자리로 보지만, 다시 선 아래로 밀리면 돌파 실패입니다.")

    if up and up["gapPct"] is not None and up["gapPct"] <= near:
        return _sig("trendline", "상승추세선 지지", "가격대", "bullish", 0.5, 2,
                    f"추세선까지 {up['gapPct']:+.1f}%",
                    "저점을 높여 온 선 바로 위에 있습니다. 여기서 받쳐 주면 추세가 "
                    "유지되는 것으로 보고, 깨면 판단이 뒤집힙니다.")

    if down and down["gapPct"] is not None and down["gapPct"] >= -near:
        return _sig("trendline", "하락추세선 저항", "가격대", "bearish", 0.5, 2,
                    f"추세선까지 {down['gapPct']:+.1f}%",
                    "고점을 낮춰 온 선 바로 아래입니다. 이 선에 막혀 되밀리는 일이 "
                    "반복돼 왔고, 뚫으면 추세 전환 신호로 봅니다.")

    if up or down:
        which = "상승" if up else "하락"
        gap = (up or down)["gapPct"]
        return _sig("trendline", f"{which}추세선 유효", "가격대", "neutral", 0.0, 1,
                    f"추세선까지 {gap:+.1f}%" if gap is not None else "-",
                    f"{which}추세선에서 떨어져 있습니다. 선에 닿거나 깰 때 다시 봅니다.")

    return None   # 방향이 맞는 스윙 점 짝이 없으면 선을 억지로 긋지 않는다


_CHECKS = (
    _c_alignment, _c_cross, _c_disparity, _c_slope, _c_macd, _c_rsi,
    _c_bollinger, _c_stochastic, _c_volume, _c_breakout, _c_levels,
    _c_trendline,
)


# ==========================================================================
# 3. 합산 · 행동 신호 · 문장
# ==========================================================================
def _composite(signals: list[dict]) -> int:
    """가중 평균을 -100~+100 으로. 중립 신호도 분모에 들어가 점수를 눌러 준다.

    (그래야 '지표 12개 중 2개만 강세'인 종목이 강한 신호로 둔갑하지 않는다.)
    """
    total = sum(s["weight"] for s in signals) or 1
    got = sum(_DIR[s["verdict"]] * s["weight"] * s["strength"] for s in signals)
    return int(round(got / total * 100))


def _band(score: int) -> str:
    for threshold, key in TA_SIGNAL_BANDS:
        if score >= threshold:
            return key
    return "strongSell"


def _action(ctx: dict, signals: list[dict], score: int) -> str:
    """종합 점수 위에 얹는 '지금 어떤 자리인가' 판정.

    점수만으로는 같은 '매수 우위'라도 이미 크게 오른 자리인지 눌린 자리인지가
    구분되지 않는다. 실제로 궁금한 건 그 차이라서 따로 본다.
    """
    by = {s["key"]: s for s in signals}
    trend_up = ctx["trend"]["direction"] == "up" and ctx["trend"]["phase"] != "혼조(중기선 아래)"
    slope = ctx["trend"]["slopePct"] or 0.0
    gap20 = _pct(ctx["price"], ctx["ma"].get(20))
    rsi_val = ctx["rsi"] or 50
    vol_bull = by.get("volume", {}).get("verdict") == "bullish"
    breakout_up = by.get("breakout", {}).get("verdict") == "bullish"
    breakdown = by.get("breakout", {}).get("verdict") == "bearish"
    cross = by.get("maCross", {})
    overheated = (rsi_val >= TA_RSI_OVERBOUGHT
                  or by.get("bollinger", {}).get("name") == "밴드 상단 돌파")

    # 아래로 깨진 자리가 가장 먼저다 — 좋은 신호와 겹쳐도 손실 관리가 우선이다.
    support_break = (by.get("levels", {}).get("name") == "지지선 근접"
                     and ctx["trend"]["direction"] == "down")
    if breakdown and slope <= 0:
        return "stopLoss"
    if support_break and score < 0:
        return "stopLoss"

    if trend_up and breakout_up and (vol_bull or slope >= 2.0) and score > 0:
        return "chase"
    if trend_up and gap20 is not None and abs(gap20) <= TA_PULLBACK_BAND \
            and 35 <= rsi_val <= 62 and score >= -10:
        return "addBuy"
    if overheated and score > 0:
        return "takeProfit"
    if cross.get("name") == "골든크로스 발생" or (score >= 25 and slope > 0):
        return "buy"
    if cross.get("name") == "데드크로스 발생" or score <= -25:
        return "reduce"
    if rsi_val <= TA_RSI_OVERSOLD and ctx["trend"]["direction"] == "down":
        return "rebound"
    return "hold"


def _headline(ctx: dict, signals: list[dict]) -> str:
    """목록·브리핑에 한 줄로 붙일 압축 표현.

    배열·기울기는 이미 `trend.label` 이 말하고 있으니 후보에서 뺀다. 안 그러면
    "정배열 · 중기 상승추세 · 이동평균 정배열" 같은 동어반복이 나온다.
    """
    trend = ctx["trend"]["label"]
    pool = [s for s in signals
            if s["verdict"] != "neutral" and s["key"] not in ("maAlign", "trendSlope")]
    if not pool:
        return trend
    strongest = max(pool, key=lambda s: s["weight"] * s["strength"])
    return f"{trend} · {strongest['name']}"


def _summary(ctx: dict, signals: list[dict], score: int) -> str:
    """2~3문장. 근거가 된 지표를 이름째로 말해 준다 (왜 그렇게 읽었는지 보이게)."""
    ranked = sorted(signals,
                    key=lambda s: abs(_DIR[s["verdict"]]) * s["weight"] * s["strength"],
                    reverse=True)
    top = [s for s in ranked if s["verdict"] != "neutral"][:3]

    # 개수를 세어서 쓴다. 판정기는 재료가 없으면 None 을 내므로 종목마다
    # 실제 신호 수가 다르다 — 상수로 박아 두면 조용히 틀린 문장이 나간다.
    lines = [f"{len(signals)}가지 차트 기법 중 강세 "
             f"{sum(1 for s in signals if s['verdict'] == 'bullish')}개 · "
             f"약세 {sum(1 for s in signals if s['verdict'] == 'bearish')}개로 "
             f"종합 {score:+d}점입니다."]
    if top:
        names = ", ".join(f"{s['name']}({s['value']})" for s in top)
        lines.append(f"가장 크게 작용한 지표는 {names}입니다.")
    lv = ctx["levels"]
    if lv.get("support") and lv.get("resistance"):
        lines.append(f"최근 흐름상 지지선은 {_fmt_num(lv['support'])}, 저항선은 "
                     f"{_fmt_num(lv['resistance'])} 부근입니다.")
    return " ".join(lines)


def brief_entry(detail: dict) -> dict | None:
    """`tickers/index.json` 과 브리핑이 함께 쓰는 압축본."""
    a = detail.get("analysis")
    if not a:
        return None
    return {
        "score": a["score"],
        "signal": a["signal"],
        "label": a["label"],
        "action": a["action"],
        "actionEmoji": a["actionEmoji"],
        "actionLabel": a["actionLabel"],
        "headline": a["headline"],
        "date": a["date"],
    }


# ==========================================================================
# 작은 도구들 — NaN 을 전부 None 으로 바꿔 JSON 계약(§7)을 지킨다
# ==========================================================================
def _list(s: pd.Series, digits: int = 2) -> list[float | None]:
    return [None if pd.isna(v) else round(float(v), digits) for v in s]


def _f(value) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _last(s: pd.Series) -> float | None:
    return _at(s, -1)


def _at(s: pd.Series, i: int) -> float | None:
    if s is None or len(s) < abs(i):
        return None
    return _f(s.iloc[i])


def _all(*values) -> bool:
    return all(v is not None for v in values)


def _pct(value, base) -> float | None:
    if value is None or not base:
        return None
    return (value - base) / base * 100


def _round(value, digits: int = 4) -> float | None:
    return None if value is None else round(float(value), digits)


def _slope_pct(s: pd.Series, span: int) -> float | None:
    """`span` 거래일 전 대비 변화율(%). 선이 눕었는지 섰는지 보는 용도."""
    clean = s.dropna()
    if len(clean) < span + 1:
        return None
    now, then = float(clean.iloc[-1]), float(clean.iloc[-span - 1])
    if not then:
        return None
    return round((now - then) / then * 100, 2)


def _fmt_num(value) -> str:
    if value is None:
        return "-"
    return f"{value:,.2f}".rstrip("0").rstrip(".") if abs(value) < 1000 else f"{value:,.0f}"
