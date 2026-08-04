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
    for sym in MACRO_SYMBOLS:
        df = prices.fetch_ohlcv(sym["key"], years=1)
        # pulse 는 2시간마다 돌아서 세션 한복판에 여러 번 걸린다. 진행 중인 봉을
        # 떨구지 않으면 지수 카드만 장중 스냅샷이 되어 종목 가격(마감)과 기준이
        # 어긋난다. 화면은 그 차이를 말해 줄 방법이 없다.
        df = prices.drop_unclosed(df, sym["market"])
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
            "spark": prices.spark(df, 30),
            "beginnerNote": sym["note"],
        })
    log.ok(f"macro: {len(out)}/{len(MACRO_SYMBOLS)} symbols")
    return out
