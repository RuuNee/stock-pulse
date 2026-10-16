"""국장 실시간·마감 숫자 — 네이버 증권 모바일 API.

세 가지를 받는다. 전부 키 없이 JSON 으로 응답한다.

* 투자자별 순매수 (외국인·기관·개인, 억 원) — 국장이 크게 움직인 날의 "왜"는 대개
  수급에서 시작한다. 2026-10-15 코스피 -7.6% 날 외국인이 하루에 3조 7,637억 원을 팔았다.
  기사 제목만 보고는 이 규모를 알 수 없다.
* 지수 현재값·마감값 (코스피·코스닥) — 장 마감 브리핑이 쓴다. FinanceDataReader 는
  마감 직후 몇 시간 동안 잠정값을 준다: 10-15 16:01 KST 에 5,535.43(-7.88%)을 줬는데
  공식 종가는 5,554.22(-7.57%)였다. 네이버는 마감 즉시 공식값이다.
* 시가총액 상위 종목의 오늘 등락 — 장 마감 브리핑의 "주요 종목" 줄.

표준 라이브러리(urllib)만 쓴다. 장 마감 브리핑 게이트가 `pip install` 전에 지수 등락을
확인해야 해서다 (pipeline/gate.py `close_mode`). 실패해도 예외를 밖으로 내지 않는다.
"""

from __future__ import annotations

import json
import urllib.request

from ..config import CALENDAR_BROWSER_UA, HTTP_TIMEOUT
from ..util import log

_BASE = "https://m.stock.naver.com/api"
_INDICES = ("KOSPI", "KOSDAQ")


def _get(path: str):
    req = urllib.request.Request(f"{_BASE}/{path}", headers={
        "User-Agent": CALENDAR_BROWSER_UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read())


def _num(value) -> float | None:
    text = str(value if value is not None else "").replace(",", "").replace("+", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# 투자자별 순매수
# --------------------------------------------------------------------------
def fetch_kr_flows() -> dict | None:
    """{"KOSPI": {date, individual, foreign, institution}, "KOSDAQ": {...}} — 억 원."""
    out: dict[str, dict] = {}
    for index in _INDICES:
        try:
            row = parse_flows(_get(f"index/{index}/trend"))
        except Exception as exc:          # 수급이 없어도 브리핑은 나간다
            log.warn(f"flows {index} skipped: {exc}")
            continue
        if row:
            out[index] = row
    return out or None


def parse_flows(data: dict) -> dict | None:
    """`{"bizdate": "20261015", "foreignValue": "-37,637", ...}` → 정수 억 원."""
    day = str(data.get("bizdate") or "")
    if len(day) != 8:
        return None
    values = {}
    for key, field in (("individual", "personalValue"), ("foreign", "foreignValue"),
                       ("institution", "institutionalValue")):
        v = _num(data.get(field))
        if v is None:
            return None
        values[key] = int(v)
    return {"date": f"{day[:4]}-{day[4:6]}-{day[6:]}", **values}


# --------------------------------------------------------------------------
# 지수
# --------------------------------------------------------------------------
def fetch_kr_indices() -> dict | None:
    """{"KOSPI": {date, close, change, changePct, closed}, "KOSDAQ": {...}}."""
    out: dict[str, dict] = {}
    for index in _INDICES:
        try:
            row = parse_index(_get(f"index/{index}/basic"))
        except Exception as exc:
            log.warn(f"index {index} skipped: {exc}")
            continue
        if row:
            out[index] = row
    return out or None


def parse_index(data: dict) -> dict | None:
    """`marketStatus` 가 CLOSE 여야 `closed=True` — 장중 값은 마감값이 아니다."""
    close, change, pct = (_num(data.get(k)) for k in
                          ("closePrice", "compareToPreviousClosePrice", "fluctuationsRatio"))
    traded = str(data.get("localTradedAt") or "")[:10]
    if close is None or pct is None or len(traded) != 10:
        return None
    # 하락일 때 compareToPreviousClosePrice 는 부호 없이 오고, 방향은 fluctuationsRatio 가 안다.
    if change is not None and pct < 0 < change:
        change = -change
    return {"date": traded, "close": close, "change": change, "changePct": pct,
            "closed": str(data.get("marketStatus") or "").upper() == "CLOSE"}


# --------------------------------------------------------------------------
# 시가총액 상위 종목
# --------------------------------------------------------------------------
def fetch_kr_leaders(n: int = 8) -> list[dict]:
    """코스피 시가총액 상위 `n` 종목의 오늘 등락. 우선주는 본주와 겹쳐서 뺀다."""
    try:
        data = _get(f"stocks/marketValue/KOSPI?page=1&pageSize={n + 6}")
    except Exception as exc:
        log.warn(f"leaders skipped: {exc}")
        return []
    return parse_leaders(data, n)


def parse_leaders(data: dict, n: int) -> list[dict]:
    out = []
    for s in (data or {}).get("stocks") or []:
        name = str(s.get("stockName") or "")
        pct, close = _num(s.get("fluctuationsRatio")), _num(s.get("closePrice"))
        if not name or pct is None or name.endswith(("우", "우B")) or "우(" in name:
            continue
        out.append({"code": s.get("itemCode"), "name": name, "close": close,
                    "changePct": pct, "date": str(s.get("localTradedAt") or "")[:10]})
        if len(out) >= n:
            break
    return out


def eok_label(value: int) -> str:
    """-37637 → '-3조 7,637억', 2228 → '+2,228억'. 브리핑에서 바로 읽히는 꼴로."""
    sign = "+" if value > 0 else "-" if value < 0 else ""
    v = abs(value)
    jo, eok = divmod(v, 10_000)
    if jo:
        return f"{sign}{jo}조" + (f" {eok:,}억" if eok else "")
    return f"{sign}{eok:,}억"
