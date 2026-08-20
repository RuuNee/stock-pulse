"""Text normalisation, de-duplication keys and sentiment heuristics."""

from __future__ import annotations

import hashlib
import html
import re
from urllib.parse import parse_qs, urlparse, urlunparse

from ..config import (
    NEGATIVE_WORDS_EN,
    NEGATIVE_WORDS_KR,
    POSITIVE_WORDS_EN,
    POSITIVE_WORDS_KR,
)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_NOISE_RE = re.compile(r"[\[\]【】\(\)<>“”\"'‘’·…|]")
# Trailing " - 매체명" that Google News appends to every headline.
_GOOGLE_SUFFIX_RE = re.compile(r"\s+-\s+[^-]{2,25}$")

TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "igshid", "ref", "cmpid", "mod", "yptr",
}


def clean_html(value: str | None) -> str:
    if not value:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", value))
    return _WS_RE.sub(" ", text).strip()


def strip_source_suffix(title: str) -> str:
    """Google News headlines end with ' - 연합뉴스'. Drop it."""
    return _GOOGLE_SUFFIX_RE.sub("", title).strip()


def normalize_url(url: str) -> str:
    """Drop tracking params + fragments so the same article dedupes cleanly."""
    if not url:
        return ""
    try:
        parts = urlparse(url)
    except ValueError:
        return url
    kept = {
        k: v for k, v in parse_qs(parts.query).items()
        if k.lower() not in TRACKING_PARAMS
    }
    query = "&".join(f"{k}={v[0]}" for k, v in sorted(kept.items()))
    return urlunparse((parts.scheme, parts.netloc.lower(), parts.path.rstrip("/"),
                       "", query, ""))


def dedup_key(title: str, url: str) -> str:
    """Same article from two feeds should collapse to one key."""
    norm = _NOISE_RE.sub("", strip_source_suffix(title)).lower()
    norm = _WS_RE.sub("", norm)
    if len(norm) >= 12:
        return "t:" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]
    return "u:" + hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:16]


def news_id(url: str) -> str:
    return hashlib.sha1(normalize_url(url).encode("utf-8")).hexdigest()[:8]


def truncate(value: str, limit: int, suffix: str = "…") -> str:
    value = value.strip()
    return value if len(value) <= limit else value[: limit - len(suffix)].rstrip() + suffix


def sentiment_of(text: str) -> str:
    """Cheap lexicon sentiment. Only used when the LLM is unavailable."""
    low = text.lower()
    pos = sum(1 for w in POSITIVE_WORDS_KR if w in text)
    neg = sum(1 for w in NEGATIVE_WORDS_KR if w in text)
    pos += sum(1 for w in POSITIVE_WORDS_EN if w in low)
    neg += sum(1 for w in NEGATIVE_WORDS_EN if w in low)
    if pos > neg:
        return "positive"
    if neg > pos:
        return "negative"
    return "neutral"


def contains_token(haystack: str, needle: str, *, case_sensitive: bool = False) -> bool:
    """Word-ish containment.

    Korean has no spaces between morphemes so substring matching is the norm,
    but bare ASCII tickers need boundaries or ``V`` matches every sentence.

    Word boundaries alone are not enough for ticker symbols: matched
    case-insensitively, ``LOW``/``NOW``/``COST``/``ALL`` hit ordinary English
    prose ("a low rate", "now moving higher"), and ``MRNA`` hits the molecule
    ``mRNA``. Measured on one day's feed, that was 8 false tags out of 105 US
    items. Headlines write symbols in caps, so callers pass
    ``case_sensitive=True`` for those.
    """
    if not needle:
        return False
    if needle.isascii() and needle.isalnum():
        flags = 0 if case_sensitive else re.IGNORECASE
        return re.search(rf"(?<![A-Za-z0-9]){re.escape(needle)}(?![A-Za-z0-9])",
                         haystack, flags) is not None
    return needle in haystack
