"""Importance scoring and categorisation for the news feed.

The brief only has room for ~6 stories a day, so ranking is what decides
whether the notification is useful or noise.
"""

from __future__ import annotations

from ..config import IMPORTANT_KEYWORDS_EN, IMPORTANT_KEYWORDS_KR
from ..util import text as T
from ..util.dates import now_utc, parse_iso

CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("정책", ("금리", "기준금리", "연준", "FOMC", "한국은행", "정부", "규제", "관세", "세금",
              "fed", "fomc", "rate", "tariff", "regulat", "policy", "treasury")),
    ("실적", ("실적", "영업이익", "매출", "어닝", "가이던스", "컨센서스",
              "earnings", "revenue", "profit", "guidance", "eps")),
    ("산업", ("반도체", "배터리", "자동차", "바이오", "조선", "방산", "AI", "전기차",
              "chip", "semiconductor", "battery", "energy", "pharma")),
    ("국제", ("중국", "미국", "일본", "유럽", "전쟁", "무역", "지정학",
              "china", "europe", "war", "geopolit", "trade")),
    ("암호화폐", ("비트코인", "이더리움", "가상자산", "코인", "bitcoin", "crypto", "ethereum")),
    ("시장", ("코스피", "코스닥", "지수", "증시", "환율", "외국인", "기관",
              "stocks", "market", "index", "s&p", "nasdaq", "dow")),
]


def categorize(item: dict) -> str:
    haystack = f"{item.get('title', '')} {item.get('summary', '')}"
    low = haystack.lower()
    if item.get("tickers"):
        best = max(t.get("score", 0) for t in item["tickers"])
        if best >= 0.85:
            return "종목"
    for label, keywords in CATEGORY_RULES:
        if any(k in haystack or k.lower() in low for k in keywords):
            return label
    return "시장"


def importance(item: dict) -> int:
    """0-100. Weights documented in md파일/02-데이터스키마.md §5."""
    score = 0.0

    # Outlet credibility (30)
    score += float(item.get("sourceWeight", 0.7)) * 30

    # Freshness (20) — full marks under 3h, nothing after 48h
    published = parse_iso(item.get("publishedAt"))
    if published:
        hours = (now_utc() - published).total_seconds() / 3600
        score += 20 * max(0.0, min(1.0, (48 - hours) / 45))
    else:
        score += 8

    # Mentions a tracked ticker (20)
    if item.get("tickers"):
        score += 20 * max(t.get("score", 0) for t in item["tickers"])

    # Market-moving keywords (20)
    haystack = f"{item.get('title', '')} {item.get('summary', '')}"
    low = haystack.lower()
    hits = sum(1 for k in IMPORTANT_KEYWORDS_KR if k in haystack)
    hits += sum(1 for k in IMPORTANT_KEYWORDS_EN if k in low)
    score += min(hits, 4) * 5

    # Reported by several outlets (10)
    score += min(item.get("dupCount", 1) - 1, 5) * 2

    return max(0, min(100, round(score)))


def enrich(items: list[dict]) -> list[dict]:
    for item in items:
        item["category"] = categorize(item)
        item["importance"] = importance(item)
        item["sentiment"] = T.sentiment_of(f"{item.get('title', '')} {item.get('summary', '')}")
        item["tags"] = _tags(item)
        item.pop("_dedup", None)
    items.sort(key=lambda x: x["importance"], reverse=True)
    return items


def _tags(item: dict) -> list[str]:
    haystack = f"{item.get('title', '')} {item.get('summary', '')}"
    tags: list[str] = []
    for label, keywords in CATEGORY_RULES:
        for keyword in keywords:
            if keyword in haystack and keyword not in tags and not keyword.isascii():
                tags.append(keyword)
    for ticker in item.get("tickers", [])[:2]:
        if ticker["name"] not in tags:
            tags.append(ticker["name"])
    return tags[:5]
