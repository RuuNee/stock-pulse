"""국장 투자자별 매매동향 — 외국인·기관·개인 순매수 (네이버 증권 모바일 API).

국장이 크게 움직인 날의 "왜"는 대개 수급에서 시작한다. 2026-10-15 코스피 -7.6% 날
외국인이 하루에 3조 7,637억 원을 팔았다 — 기사 제목만 보고는 이 규모를 알 수 없다.
지수 등락률만 싣던 브리핑이 원인을 말하려면 이 숫자가 필요하다.

키 없이 JSON 으로 응답한다. 단위는 억 원. 실패해도 브리핑은 나가야 하므로 예외를
밖으로 내지 않고 None 을 돌려준다.
"""

from __future__ import annotations

import requests

from ..config import CALENDAR_BROWSER_UA, HTTP_TIMEOUT
from ..util import log

_URL = "https://m.stock.naver.com/api/index/{index}/trend"
_INDICES = ("KOSPI", "KOSDAQ")


def fetch_kr_flows() -> dict | None:
    """{"KOSPI": {date, individual, foreign, institution}, "KOSDAQ": {...}} — 억 원."""
    out: dict[str, dict] = {}
    for index in _INDICES:
        try:
            r = requests.get(_URL.format(index=index), timeout=HTTP_TIMEOUT,
                             headers={"User-Agent": CALENDAR_BROWSER_UA})
            r.raise_for_status()
            row = parse(r.json())
        except Exception as exc:          # 수급이 없어도 브리핑은 나간다
            log.warn(f"flows {index} skipped: {exc}")
            continue
        if row:
            out[index] = row
    return out or None


def parse(data: dict) -> dict | None:
    """`{"bizdate": "20261015", "foreignValue": "-37,637", ...}` → 정수 억 원."""
    day = str(data.get("bizdate") or "")
    if len(day) != 8:
        return None
    values = {}
    for key, field in (("individual", "personalValue"), ("foreign", "foreignValue"),
                       ("institution", "institutionalValue")):
        raw = str(data.get(field) or "").replace(",", "").replace("+", "").strip()
        try:
            values[key] = int(raw)
        except ValueError:
            return None
    return {"date": f"{day[:4]}-{day[4:6]}-{day[6:]}", **values}


def eok_label(value: int) -> str:
    """-37637 → '-3조 7,637억', 2228 → '+2,228억'. 브리핑에서 바로 읽히는 꼴로."""
    sign = "+" if value > 0 else "-" if value < 0 else ""
    v = abs(value)
    jo, eok = divmod(v, 10_000)
    if jo:
        return f"{sign}{jo}조" + (f" {eok:,}억" if eok else "")
    return f"{sign}{eok:,}억"
