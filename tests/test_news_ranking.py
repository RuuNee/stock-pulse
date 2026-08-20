"""뉴스 태깅·선별 회귀 — 2026-08-19 모더나 사고.

모더나 흑색종 임상 성공 기사가 브리핑에 안 나간 원인이 두 겹이었다 (99-스펙변경이력).
둘 다 조용히 되돌아갈 수 있는 종류라 고정한다.

1. 종목코드를 대소문자 무시로 매칭해서 `LOW`/`NOW` 가 평범한 영어 단어에 걸렸고,
   오태깅이 importance +20 을 받아 진짜 종목 기사를 밀어냈다.
2. 브리핑 6자리를 매크로 기사가 다 먹으면 개별 종목이 한 칸도 못 들어간다.
"""

from __future__ import annotations

from pipeline.analyze import link
from pipeline.build import brief
from pipeline.config import BRIEF_NEWS_TICKER_MIN, BRIEF_NEWS_TOTAL
from pipeline.util import text as T


def _us(code: str, name: str, name_en: str | None = None) -> dict:
    return {"code": code, "name": name, "market": "US", "exchange": "NASDAQ",
            "aliases": [], "currency": "USD", "isEtf": False, "tier": 1,
            "nameEn": name_en or name}


def _item(title: str) -> dict:
    return {"title": title, "summary": "", "tickers": []}


# --------------------------------------------------------------------------
# 1. 종목코드 오태깅
# --------------------------------------------------------------------------

def test_lowercase_word_does_not_match_ticker_symbol():
    """`LOW`(Lowe's)가 "a low rate" 에, `NOW`(ServiceNow)가 "now moving" 에 걸렸다."""
    assert not T.contains_token("Why locking in a low rate matters", "LOW",
                                case_sensitive=True)
    assert not T.contains_token("rates are now moving higher", "NOW",
                                case_sensitive=True)
    # mRNA(분자)가 MRNA(모더나 티커)로 잡히던 것도 같은 원인이다.
    assert not T.contains_token("an experimental mRNA vaccine", "MRNA",
                                case_sensitive=True)


def test_uppercase_symbol_still_matches():
    """오태깅을 막느라 진짜 심볼 언급까지 놓치면 안 된다."""
    assert T.contains_token("Apple (AAPL) rises after earnings", "AAPL",
                            case_sensitive=True)
    assert T.contains_token("ServiceNow (NOW) beats estimates", "NOW",
                            case_sensitive=True)


def test_tagging_rejects_prose_but_keeps_real_mentions():
    universe = [_us("LOW", "Lowe's"), _us("NOW", "ServiceNow"),
                _us("MRNA", "Moderna")]
    tagged = link.tag_tickers(
        [_item("Dollar Falls as Prospects Dim for a low rate rise"),
         _item("Moderna (MRNA) soars on melanoma trial success")],
        universe,
    )
    assert tagged[0]["tickers"] == [], "평범한 영어 단어에 종목이 붙었다"
    assert [t["code"] for t in tagged[1]["tickers"]] == ["MRNA"]


def test_korean_codes_stay_case_insensitive():
    """6자리 숫자 코드는 대소문자 개념이 없다 — 규칙을 US 에만 적용했는지 확인."""
    needles = dict((n, cased) for n, _, cased in
                   link._needles({"code": "005930", "name": "삼성전자",
                                  "market": "KR", "aliases": ["삼전"]}))
    assert needles["005930"] is False


# --------------------------------------------------------------------------
# 2. 브리핑 종목 쿼터
# --------------------------------------------------------------------------

def _scored(title: str, importance: int, tickers: list[str] | None = None) -> dict:
    return {"title": title, "importance": importance,
            "tickers": [{"code": c, "name": c} for c in (tickers or [])]}


def test_ticker_news_keeps_a_seat_when_macro_sweeps_the_top():
    """매크로가 상위를 다 먹어도 개별 종목 자리는 남는다."""
    news = [_scored(f"macro {i}", 90 - i) for i in range(10)]
    news += [_scored("Moderna soars on trial success", 69, ["MRNA"]),
             _scored("Merck vaccine study succeeds", 68, ["MRK"])]
    news.sort(key=lambda n: n["importance"], reverse=True)

    picks = brief._pick_news(news)

    assert len(picks) == BRIEF_NEWS_TOTAL
    with_ticker = [n for n in picks if n["tickers"]]
    assert len(with_ticker) >= BRIEF_NEWS_TICKER_MIN
    assert any("Moderna" in n["title"] for n in picks)


def test_quota_does_not_pad_when_ticker_news_is_scarce():
    """종목 기사가 쿼터보다 적어도 자리를 비워 두거나 중복시키면 안 된다."""
    news = [_scored(f"macro {i}", 90 - i) for i in range(10)]
    news.append(_scored("only stock story", 40, ["AAPL"]))
    news.sort(key=lambda n: n["importance"], reverse=True)

    picks = brief._pick_news(news)

    assert len(picks) == BRIEF_NEWS_TOTAL
    assert len({id(n) for n in picks}) == BRIEF_NEWS_TOTAL, "같은 기사가 두 번 실렸다"


def test_picks_are_importance_ordered():
    news = [_scored(f"macro {i}", 90 - i) for i in range(10)]
    news += [_scored("stock a", 50, ["AAPL"]), _scored("stock b", 49, ["MSFT"])]
    news.sort(key=lambda n: n["importance"], reverse=True)

    scores = [n["importance"] for n in brief._pick_news(news)]
    assert scores == sorted(scores, reverse=True)


# --------------------------------------------------------------------------
# 3. 국장 브리핑의 "밤사이 미국" 블록
# --------------------------------------------------------------------------

def test_overnight_block_is_kr_only_and_ticker_scoped():
    news = [
        {"title": "US stock story", "market": "US", "importance": 60,
         "url": "u", "tickers": [{"code": "MRNA", "name": "Moderna"}]},
        {"title": "US macro story", "market": "US", "importance": 90,
         "url": "u", "tickers": []},
        {"title": "KR story", "market": "KR", "importance": 80,
         "url": "u", "tickers": [{"code": "005930", "name": "삼성전자"}]},
    ]

    kr = brief._overnight_us("KR", news)
    assert [n["title"] for n in kr] == ["US stock story"], \
        "지수 수준 매크로는 marketSnapshot 이 이미 보여준다"

    assert brief._overnight_us("US", news) == [], "미장 브리핑엔 붙지 않는다"
