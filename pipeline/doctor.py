"""`doctor` — verify every data source before relying on it.

Prints a live/dead status for price data, listings, macro symbols, and every
RSS feed. Run it monthly; when a feed dies, prune it from config and update
md파일/01-데이터소스.md.
"""

from __future__ import annotations

from .config import FEEDS, MACRO_SYMBOLS, USER_AGENT, gemini_key, telegram_token
from .util import log


def run() -> int:
    failures = 0

    log.step("가격 데이터 (FinanceDataReader)")
    from .collect import prices
    for name, sym in [("삼성전자", "005930"), ("Apple", "AAPL")]:
        df = prices.fetch_ohlcv(sym, years=1)
        if df is not None and not df.empty:
            log.ok(f"{name} ({sym}): {len(df)}행, 최근 {df.index[-1].date()}")
        else:
            log.err(f"{name} ({sym}): 실패")
            failures += 1

    log.step("유니버스 목록")
    from .collect import universe
    meta = universe.enrich()
    kr = sum(1 for m in meta if m["market"] == "KR" and m.get("marcap"))
    log.ok(f"메타데이터 병합: {len(meta)}종목 (시총 확보 KR {kr})")

    log.step("매크로 심볼")
    for sym in MACRO_SYMBOLS:
        df = prices.fetch_ohlcv(sym["key"], years=1)
        if df is not None and not df.empty:
            log.ok(f"{sym['name']} ({sym['key']}): {float(df['Close'].iloc[-1]):,.2f}")
        else:
            log.err(f"{sym['name']} ({sym['key']}): 실패")
            failures += 1

    log.step("RSS 피드")
    import feedparser
    live = dead = 0
    for key, feed in FEEDS.items():
        try:
            parsed = feedparser.parse(feed["url"], agent=USER_AGENT)
            n = len(parsed.entries)
        except Exception as exc:
            log.err(f"{key}: 오류 {exc}")
            dead += 1
            continue
        if n:
            log.ok(f"{key} ({feed['market']}): {n}건")
            live += 1
        else:
            log.err(f"{key}: 빈 응답 — config에서 제거 검토")
            dead += 1
    log.info(f"피드 요약: {live} 정상 / {dead} 죽음")

    log.step("종목별 뉴스 경로")
    from .collect import news
    kr_probe = news.fetch_ticker_news({"code": "005930", "name": "삼성전자", "market": "KR"})
    us_probe = news.fetch_ticker_news({"code": "AAPL", "name": "Apple", "market": "US"})
    log.ok(f"Google News(국장) {len(kr_probe)}건 / Yahoo(미장) {len(us_probe)}건")

    log.step("시크릿")
    log.ok(f"GEMINI_API_KEY: {'있음 (LLM 요약·번역 활성)' if gemini_key() else '없음 (규칙 기반 폴백, 번역 없음)'}")
    log.ok(f"TELEGRAM_BOT_TOKEN: {'있음' if telegram_token() else '없음'}")

    log.step("결과")
    if failures:
        log.err(f"{failures}개 핵심 소스 실패 — 위 로그 확인")
    else:
        log.ok("핵심 데이터 소스 정상")
    return 1 if failures else 0
