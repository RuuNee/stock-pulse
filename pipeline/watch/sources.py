"""감시 소스 파싱 — RSS 를 공통 항목으로 바꾸고, 항목을 대상 종목에 붙인다.

공통 항목(dict)
    id           소스 안에서 유일한 값 (DART 는 접수번호)
    source       "dart" | "prnewswire" | "newsroom:NVDA" | 뉴스 피드 키(config.FEEDS)
    official     회사·거래소가 직접 낸 것(공시·보도자료·뉴스룸)인지
    title, summary, url
    publishedAt  datetime(UTC) 또는 None
    market       "KR" | "US" | None
    meta         소스별 정보 — DART: cls/corp/report/rcpNo, 뉴스룸: ticker
"""

from __future__ import annotations

import calendar
import hashlib
import re
from datetime import datetime, timezone

from ..util import text as T

# --------------------------------------------------------------------------
# RSS
# --------------------------------------------------------------------------


def parse_feed(body: bytes, *, source: str, official: bool, market: str | None = None,
               limit: int = 60) -> list[dict]:
    import feedparser
    parsed = feedparser.parse(body)
    out: list[dict] = []
    for entry in (parsed.entries or [])[:limit]:
        title = T.clean_html(entry.get("title"))
        if not title:
            continue
        url = (entry.get("link") or "").strip()
        guid = (entry.get("id") or entry.get("guid") or url or title).strip()
        out.append({
            "id": f"{source}:{hashlib.blake2b(guid.encode(), digest_size=8).hexdigest()}",
            "source": source,
            "official": official,
            "title": title,
            "summary": T.truncate(T.clean_html(entry.get("summary") or entry.get("description")), 400),
            "url": url,
            "publishedAt": _published(entry),
            "market": market,
            "meta": {},
        })
    return out


def _published(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            try:
                return datetime.fromtimestamp(calendar.timegm(value), tz=timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
    return None


# --------------------------------------------------------------------------
# DART — "(코스닥)회사명 - 보고서명" 제목을 나눈다
# --------------------------------------------------------------------------
_DART_TITLE = re.compile(r"^\((유가|코스닥|코넥스|기타)\)\s*(.+?)\s+-\s+(.+)$")

# 주가를 움직일 수 있는 보고서. 보고서명에 이 말이 들어 있으면 본다(띄어쓰기 무시).
DART_MATERIAL = (
    "단일판매", "공급계약", "유상증자", "무상증자", "감자", "자기주식", "주식소각",
    "최대주주", "합병", "분할", "영업양수", "영업양도", "자산양수", "자산양도",
    "타법인주식", "유형자산", "신규시설투자", "영업정지", "생산중단", "회생", "파산",
    "부도", "해산", "상장폐지", "관리종목", "매매거래정지", "불성실공시", "횡령", "배임",
    "소송", "조회공시", "풍문", "잠정", "매출액또는손익구조", "공개매수", "임상",
    "품목허가", "기술이전", "기술도입", "전환사채", "신주인수권부사채", "교환사채",
    "현금ㆍ현물배당", "주식배당", "투자판단관련주요경영사항", "대표이사", "채무인수",
    "채무보증", "특허", "수주",
)
# 절차·서식 보고서 — 위 말이 섞여 있어도 주가 재료가 아니다.
DART_SKIP = (
    "임원ㆍ주요주주특정증권등소유상황보고서", "증권발행실적보고서", "투자설명서",
    "일괄신고", "특수관계인", "대규모기업집단", "기업지배구조보고서", "지속가능경영",
    "주주총회소집", "기업설명회",
)


def parse_dart(body: bytes) -> list[dict]:
    items = parse_feed(body, source="dart", official=True, market="KR", limit=60)
    for item in items:
        match = _DART_TITLE.match(item["title"])
        if match:
            item["meta"] = {"cls": match.group(1), "corp": match.group(2).strip(),
                            "report": match.group(3).strip()}
        rcp = re.search(r"rcpNo=(\d+)", item["url"])
        if rcp:
            item["meta"]["rcpNo"] = rcp.group(1)
            item["id"] = f"dart:{rcp.group(1)}"
    return items


def dart_material(report: str) -> bool:
    flat = (report or "").replace(" ", "")
    if any(word in flat for word in DART_SKIP):
        return False
    return any(word in flat for word in DART_MATERIAL)


def dart_routine(report: str) -> bool:
    """절차·서식 보고서 — 대상 종목 것이라도 판정(Claude)에 넘기지 않는다."""
    flat = (report or "").replace(" ", "")
    return any(word in flat for word in DART_SKIP)


def dart_listed(item: dict) -> bool:
    """유가증권·코스닥 상장사만. 코넥스·기타(비상장)는 개인 투자자 대상이 아니다."""
    return (item.get("meta") or {}).get("cls") in ("유가", "코스닥")


# --------------------------------------------------------------------------
# 보도자료 — "(NASDAQ: XXX)" 표기
# --------------------------------------------------------------------------
_WIRE_TAG = re.compile(
    r"\((?:NASDAQ|Nasdaq|NYSE(?: American| Arca)?|Cboe BZX)\s*:\s*([A-Z][A-Z0-9.\-]{0,6})\)")


def wire_tickers(item: dict) -> list[str]:
    hay = f"{item.get('title', '')} {item.get('summary', '')}"
    return list(dict.fromkeys(_WIRE_TAG.findall(hay)))


# 판정(Claude)을 못 할 때 공식 발표 중 이것만은 보낸다.
_STRONG_WORDS = re.compile(
    r"\b(acqui|merger|merge|CEO|chief executive|resign|reinstat|appoint|guidance|"
    r"results|earnings|recall|investigation|subpoena|FDA|approv|bankrupt|chapter 11|"
    r"settlement|lawsuit|buyback|repurchase|dividend|split|offering|delist|halt)",
    re.IGNORECASE)


def strong_release(item: dict) -> bool:
    if item.get("source") == "dart":
        return dart_material((item.get("meta") or {}).get("report", ""))
    return bool(_STRONG_WORDS.search(item.get("title", "")))


# --------------------------------------------------------------------------
# 대상 종목에 붙이기
# --------------------------------------------------------------------------


def key_of(target: dict) -> str:
    return f"{target['market']}:{target['code']}"


def norm_kr(name: str) -> str:
    out = re.sub(r"\(주\)|㈜|주식회사|\s+", "", name or "")
    return out.upper()


class Matcher:
    """대상 종목의 이름·별칭·티커로 항목을 회사에 붙인다.

    규칙만 쓴다 — 틀리게 붙어도 즉시 판정(Claude)이 "중요하지 않다"로 거른다.
    영문 이름은 단어 경계로, 한글 이름은 부분 문자열로 찾는다. 두 글자 영문 이름
    (LG·SK)은 흔한 낱말과 겹쳐서 쓰지 않는다. 미장 티커는 보도자료의 거래소 표기와
    회사 뉴스룸으로만 붙인다(ON·ALL 같은 티커가 문장에 섞이므로).
    """

    def __init__(self, targets: list[dict]):
        self._ascii: list[tuple[re.Pattern, dict]] = []
        self._hangul: list[tuple[str, dict]] = []
        self._tickers: dict[str, dict] = {}
        self._kr_names: dict[str, dict] = {}
        for t in targets:
            names = [t.get("name") or "", t.get("nameEn") or "", *(t.get("aliases") or [])]
            if t["market"] == "US":
                self._tickers[t["code"].upper()] = t
            else:
                self._kr_names[norm_kr(t.get("name", ""))] = t
            for name in dict.fromkeys(n.strip() for n in names if n and n.strip()):
                if name.isascii():
                    if len(name) < 3:
                        continue
                    pattern = re.compile(
                        rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", re.IGNORECASE)
                    self._ascii.append((pattern, t))
                elif len(name) >= 2:
                    self._hangul.append((name, t))

    def match(self, item: dict) -> list[dict]:
        found: dict[str, dict] = {}
        meta = item.get("meta") or {}
        if item.get("source") == "dart":
            # 공시는 회사가 제목에 정해져 있다 — 보고서명 속 다른 회사 이름으로 붙이지 않는다.
            hit = self._kr_names.get(norm_kr(meta.get("corp", "")))
            return [hit] if hit else []
        if meta.get("ticker"):
            hit = self._tickers.get(meta["ticker"])
            return [hit] if hit else []
        for ticker in wire_tickers(item):
            hit = self._tickers.get(ticker)
            if hit:
                found[key_of(hit)] = hit
        hay = f"{item.get('title', '')} {item.get('summary', '')}"
        for pattern, t in self._ascii:
            if pattern.search(hay):
                found[key_of(t)] = t
        for name, t in self._hangul:
            if name in hay:
                found[key_of(t)] = t
        return list(found.values())
