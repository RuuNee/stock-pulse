"""브리핑 뉴스 후보 고르기 — 증시와 무관한 기사·같은 사건 중복·지난 브리핑 재탕을 거른다.

`importance`(analyze/score.py)는 전체 피드 순위용이라 브리핑에 그대로 쓰면 세 가지가
샌다. 전부 실제 브리핑에서 본 것들이다.

1. **무관한 기사** — 일반 경제 피드(연합·경향·한겨레)에는 치매 예방 캠페인, 편의점
   김밥 나트륨 같은 기사가 섞인다. 언론사 가중치와 신선도만으로 60점대가 나온다.
   2026-10-15 에는 "[게시판] 소비자원 …"(66점)이 "코스피·코스닥 동시 서킷브레이커"
   (48점)보다 위였다.
2. **같은 사건 중복** — 2026-10-15 국장 브리핑 6자리 중 3자리가 신한지주의 롯데손보
   인수(연합·매경·한경)였다.
3. **어제 것 재탕** — 같은 기사가 이틀 연속 실렸다 (10-06·10-07 "코스피 7100…").

여기서 고른 후보를 LLM 이 최종 선택한다. LLM 이 없으면 `build/brief._pick_news` 가
이 후보 순서대로 고른다.
"""

from __future__ import annotations

import re
from datetime import datetime

from ..config import (
    BRIEF_CANDIDATES,
    BRIEF_CANDIDATES_PER_TICKER,
    BRIEF_US_CANDIDATES,
    MARKET_TERMS_EN,
    MARKET_TERMS_KR,
    MARKET_WIDE_RE,
    NEWS_JUNK_PATTERNS,
)
from ..util.dates import parse_iso

_JUNK = [re.compile(p) for p in NEWS_JUNK_PATTERNS]
_MARKET_WIDE = re.compile(MARKET_WIDE_RE, re.IGNORECASE)
_TAGS = re.compile(r"\[[^\]]*\]|\([^)]*\)|【[^】]*】|<[^>]*>")
_NOT_WORD = re.compile(r"[^0-9A-Za-z가-힣]+")
_EN_WORD = re.compile(r"[a-z][a-z&\-]+")

MARKET_WIDE_BONUS = 12     # 지수 전체가 움직인 사건 — 브리핑의 1순위 재료
SIMILAR_TITLE = 0.42       # 제목 글자쌍 겹침이 이 이상이면 같은 사건으로 본다


def is_junk(item: dict) -> bool:
    title = item.get("title") or ""
    return any(p.search(title) for p in _JUNK)


def is_market_relevant(item: dict) -> bool:
    """종목 태그가 있거나, 제목·요약에 증시 용어가 하나라도 있으면 후보."""
    if item.get("tickers"):
        return True
    text = f"{item.get('title', '')} {item.get('summary', '')}"
    if any(term in text for term in MARKET_TERMS_KR):
        return True
    words = set(_EN_WORD.findall(text.lower()))
    low = text.lower()
    return any((term in words) if " " not in term else (term in low) for term in MARKET_TERMS_EN)


def is_market_wide(item: dict) -> bool:
    return bool(_MARKET_WIDE.search(item.get("title") or ""))


def bigrams(title: str) -> set[str]:
    """`[특징주]`·`(종합)` 같은 꼬리표를 떼고 글자쌍으로. 띄어쓰기·문장부호는 무시한다."""
    core = _NOT_WORD.sub("", _TAGS.sub(" ", title or "")).lower()
    return {core[i:i + 2] for i in range(len(core) - 1)}


def similarity(a: str, b: str) -> float:
    x, y = bigrams(a), bigrams(b)
    if not x or not y:
        return 0.0
    return len(x & y) / len(x | y)


def brief_score(item: dict) -> int:
    """브리핑 후보 순위 점수 = importance + 시장 전체 사건 가산점."""
    return int(item.get("importance") or 0) + (MARKET_WIDE_BONUS if is_market_wide(item) else 0)


def candidates(news: list[dict], market: str, *, since: datetime | None = None,
               exclude_urls: set[str] | None = None,
               limit: int = BRIEF_CANDIDATES) -> list[dict]:
    """브리핑 후보. 각 항목은 원본의 얕은 복사에 `briefScore`·`related` 를 붙인 것.

    국장 브리핑에는 미국 기사 상위 `BRIEF_US_CANDIDATES` 건을 같이 넣는다 —
    밤사이 미국 소식은 한국 투자자가 아침에 처음 보는 정보다.
    """
    exclude_urls = exclude_urls or set()
    home = [n for n in news if n.get("market") in (market, "GLOBAL")]
    pool = _filter(home, since, exclude_urls)
    if market == "KR" and BRIEF_US_CANDIDATES:
        us = _filter([n for n in news if n.get("market") == "US"], since, exclude_urls)
        us = [n for n in us if n.get("tickers") or is_market_wide(n)]
        us.sort(key=brief_score, reverse=True)
        pool += us[:BRIEF_US_CANDIDATES]

    pool = [dict(n, briefScore=brief_score(n)) for n in pool]
    pool.sort(key=lambda n: n["briefScore"], reverse=True)
    return cluster(pool, limit=limit)


def _filter(items: list[dict], since, exclude_urls) -> list[dict]:
    out = []
    for n in items:
        if n.get("url") in exclude_urls or is_junk(n) or not is_market_relevant(n):
            continue
        if since is not None:
            published = parse_iso(n.get("publishedAt"))
            if published is not None and published < since:
                continue
        out.append(n)
    return out


def cluster(pool: list[dict], *, limit: int) -> list[dict]:
    """점수 순으로 돌며 같은 사건이면 앞선 기사에 묶는다. 묶인 제목은 `related` 로 남긴다.

    제목이 많이 겹치면(SIMILAR_TITLE) 같은 사건이다. 그것만으로는 부족하다 —
    "신한지주 4.7% 하락" 과 "승자의 저주 걱정에 롯데손보 삼킨 신한지주 급락" 은 글자로는
    별로 안 겹치지만 같은 이야기다. 그래서 같은 종목이 주인공인 기사는
    `BRIEF_CANDIDATES_PER_TICKER` 건까지만 두고 나머지는 버린다. 같은 사건인지 확실하지
    않으므로 `related` 에는 넣지 않는다 (LLM 이 "여러 매체가 다룬 사건"으로 오해한다).
    """
    kept: list[dict] = []
    per_ticker: dict[str, int] = {}
    for item in pool:
        twin = next((k for k in kept
                     if similarity(k.get("title", ""), item.get("title", "")) >= SIMILAR_TITLE),
                    None)
        if twin is not None:
            # 같은 사건을 다룬 매체 수는 그 자체로 중요도 신호라 제목을 남긴다.
            twin["related"].append(item.get("title", ""))
            continue
        lead = _lead_ticker(item)
        if lead and per_ticker.get(lead, 0) >= BRIEF_CANDIDATES_PER_TICKER:
            continue        # 같은 종목 기사는 이미 충분하다 (같은 사건인지는 모른다)
        item = dict(item, related=[])
        kept.append(item)
        if lead:
            per_ticker[lead] = per_ticker.get(lead, 0) + 1
        if len(kept) >= limit:
            break
    return kept


def _lead_ticker(item: dict) -> str | None:
    tickers = item.get("tickers") or []
    return tickers[0].get("code") if tickers else None
