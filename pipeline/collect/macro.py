"""Macro dashboard data — indices, FX, rates, commodities (schema §2)."""

from __future__ import annotations

from ..config import DATA_DIR, MACRO_SYMBOLS
from ..util import io, log
from . import prices


def _previous_entries() -> dict[str, dict]:
    """직전에 쓴 지수 항목. 소스가 뒤로 갈 때 그대로 이어받는다."""
    prev = io.read_json(DATA_DIR / "market" / "overview.json", {}) or {}
    return {i["key"]: i for i in prev.get("indices", []) if i.get("date")}


def collect() -> list[dict]:
    # 종목과 같은 이유 — 소스가 직전 세션 봉을 잠깐 빼고 줄 때가 있다
    # (build/site_data.py `_no_backslide` 참고). 지수는 pulse 가 2시간마다
    # 다시 만들어 저절로 복구되지만, 그 사이 홈 화면의 지수 날짜만 하루
    # 뒤로 가서 종목 화면과 어긋나 보인다.
    seen = _previous_entries()
    out: list[dict] = []
    frames: dict = {}
    for sym in MACRO_SYMBOLS:
        df = prices.fetch_ohlcv(sym["key"], years=1)
        # pulse 는 2시간마다 돌아서 세션 한복판에 여러 번 걸린다. 진행 중인 봉을
        # 떨구지 않으면 지수 카드만 장중 스냅샷이 되어 종목 가격(마감)과 기준이
        # 어긋난다. 화면은 그 차이를 말해 줄 방법이 없다.
        # 마감 판정은 상장된 시장 기준이다 — EWY 는 국장 화면에 나오지만 미국 상장이다.
        df = prices.drop_unclosed(df, sym.get("closeMarket", sym["market"]))
        if df is None or df.empty:
            log.warn(f"macro skip: {sym['key']}")
            continue
        quote = prices.quote_from(df)
        was = seen.get(sym["key"])
        if was and quote.get("date") and quote["date"] < was["date"]:
            # 빼 버리면 안 된다 — `_build_overview` 가 `indices` 를 통째로
            # 교체하므로, 건너뛰면 그 지수가 홈 화면에서 사라진다.
            log.warn(f"macro {sym['key']}: 소스가 뒤로 감 "
                     f"({was['date']} → {quote['date']}) — 이전 값 유지")
            out.append(was)
            continue
        frames[sym["key"]] = df
        out.append({
            "key": sym["key"],
            "name": sym["name"],
            "market": sym["market"],
            "group": sym["group"],
            "unit": sym["unit"],
            # 어느 날 마감인지 화면이 말할 수 있어야 한다. 없으면 "왜 안 움직이지"가
            # 곧바로 "고장났나"로 읽힌다.
            "date": quote.get("date"),
            "value": quote.get("close"),
            "change": quote.get("change"),
            "changePct": quote.get("changePct"),
            **trend(df),
            "spark": prices.spark(df, 30),
            "beginnerNote": sym["note"],
        })
    ewy = next((i for i in out if i["key"] == "EWY"), None)
    if ewy is not None and {"EWY", "KS11", "USD/KRW"} <= frames.keys():
        ewy["overnightGap"] = korea_overnight_gap(frames["EWY"], frames["KS11"],
                                                  frames["USD/KRW"])
    log.ok(f"macro: {len(out)}/{len(MACRO_SYMBOLS)} symbols")
    return out


def korea_overnight_gap(ewy, kospi, fx, *, window: int = 20) -> float | None:
    """코스피 마감 뒤 미국장에서 한국 주식이 더 움직인 몫 (%) — 다음 날 시가의 예고.

    EWY 의 하루 등락을 그대로 쓰면 안 된다. EWY 의 D일 봉(미국 시각)에는 그날
    코스피 장중 움직임이 이미 들어 있어서, 2026-10-15 처럼 코스피가 -7.6% 빠진 날
    밤 EWY 도 -6% 대로 따라 내려간다. 그걸 "밤사이 또 급락"으로 읽으면 끝난 하락을
    한 번 더 세는 셈이다. 같은 날짜끼리 빼는 것도 틀린다 — 셈을 풀면 "오늘 밤 몫 −
    어젯밤 몫"이 된다.

    대신 두 가격의 **비율**을 본다. R = EWY ÷ (코스피 ÷ 원달러). 평소 R 은 거의
    일정하고, 코스피가 닫힌 뒤 EWY 만 움직이면 그만큼 벗어난다. 최근 `window` 거래일
    R 의 중앙값을 기준으로 지금 R 이 몇 % 벗어났는지가 답이다.
    2026-03~10 실측: 다음 날 코스피 시가 갭과 상관 0.65 / 평균 오차 1.6%p.
    (EWY 등락 그대로는 0.51 / 2.7%p, 같은 날짜끼리 빼기는 0.51 / 2.7%p.)

    EWY 마지막 봉이 코스피 마지막 봉보다 오래됐으면(미국 휴장) 새 정보가 없으므로 None.
    """
    try:
        e, k = ewy["Close"].dropna(), kospi["Close"].dropna()
        f = fx["Close"].dropna()
        if len(k) < 6 or e.empty or f.empty or e.index[-1] < k.index[-1]:
            return None
        f = f.reindex(k.index.union(e.index)).ffill()
        ratio_now = e.iloc[-1] / (k.iloc[-1] / f.loc[e.index[-1]])
        hist = []
        for d in k.index[-window - 1:-1]:          # 오늘 코스피 봉은 기준에서 뺀다
            if d in e.index and d in f.index and f.loc[d] > 0:
                hist.append(e.loc[d] / (k.loc[d] / f.loc[d]))
        if len(hist) < 5:
            return None
        base = sorted(hist)[len(hist) // 2]
        return round((ratio_now / base - 1) * 100, 2)
    except Exception:                              # 데이터 꼴이 이상하면 신호를 안 쓴다
        return None


def trend(df) -> dict:
    """하루치 등락만으로는 "흐름"을 말할 수 없다.

    2026-10-15 코스피 -7.6% 는 하루짜리 사건이 아니라 7거래일 연속 하락(약 -20%)의
    끝이었다. 브리핑 해설이 "최근 1주 -14%, 연고점 대비 -21%" 같은 맥락을 쓰려면
    숫자가 있어야 한다. 세 값 모두 종가 기준 % 이고, 데이터가 모자라면 None.
    """
    closes = df["Close"]
    last = float(closes.iloc[-1])

    def change_over(n: int):
        if len(closes) <= n:
            return None
        base = float(closes.iloc[-1 - n])
        return round((last / base - 1) * 100, 2) if base else None

    high = float(closes.tail(252).max())
    return {
        "change5d": change_over(5),
        "change20d": change_over(20),
        "fromHigh52w": round((last / high - 1) * 100, 2) if high else None,
    }
