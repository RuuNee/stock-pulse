"""Macro dashboard data — indices, FX, rates, commodities (schema §2)."""

from __future__ import annotations

from ..config import MACRO_SYMBOLS
from ..util import log
from . import prices


def collect() -> list[dict]:
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
