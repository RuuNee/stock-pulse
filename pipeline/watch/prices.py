"""시세 — 네이버 실시간 시세로 대상 종목을 몇 초마다 보고 급변을 잡는다.

뉴스보다 가격이 먼저 움직인다. 11/23 엔비디아는 회사 발표(08:55:00 ET)와 같은 분에
+8% → +19% 로 뛰었다. 발표 창구를 모르는 종목도 시세 급변으로는 잡힌다.

네이버 실시간 시세(키 불필요, 2026-11-24 실측)
* 국장  /api/realtime/domestic/stock/005930,000660      정규장 + 넥스트레이드 프리·애프터
* 미장  /api/realtime/worldstock/stock/NVDA.O,XOM      정규장 + 프리·애프터마켓
  - 코드: 나스닥은 `.O` 를 붙이고, 뉴욕·아멕스는 티커 그대로, 클래스주는 `BRKb`.
    처음엔 후보를 다 보내 보고 돌아온 것으로 정한다(틀린 코드는 응답에서 빠질 뿐).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from ..config import (
    WATCH_INCIDENT_MIN,
    WATCH_MOVE_1M_PCT,
    WATCH_MOVE_5M_PCT,
    WATCH_MOVE_STEP_PCT,
    WATCH_QUOTE_KR_URL,
    WATCH_QUOTE_US_URL,
)

_BATCH = 40   # 한 요청에 넣는 코드 수


@dataclass
class Quote:
    market: str
    code: str
    price: float | None
    day_pct: float | None      # 정규장은 전일 종가 대비, 프리·애프터는 직전 정규장 종가 대비
    session: str               # "regular" | "pre" | "after" | "closed"
    currency: str

    @property
    def key(self) -> str:
        return f"{self.market}:{self.code}"


def _num(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return None


def _session(row: dict) -> tuple[str, float | None, float | None]:
    if (row.get("marketStatus") or "").upper() == "OPEN":
        return "regular", _num(row.get("closePrice")), _num(row.get("fluctuationsRatio"))
    over = row.get("overMarketPriceInfo") or {}
    if (over.get("overMarketStatus") or "").upper() == "OPEN":
        kind = (over.get("tradingSessionType") or "").upper()
        return ("pre" if kind.startswith("PRE") else "after",
                _num(over.get("overPrice")), _num(over.get("fluctuationsRatio")))
    return "closed", _num(row.get("closePrice")), _num(row.get("fluctuationsRatio"))


def parse_kr(payload: dict | None) -> dict[str, Quote]:
    out: dict[str, Quote] = {}
    for row in (payload or {}).get("datas") or []:
        code = row.get("itemCode") or row.get("symbolCode")
        if not code:
            continue
        session, price, pct = _session(row)
        out[code] = Quote("KR", code, price, pct, session, "KRW")
    return out


def _symbol(row: dict) -> str:
    """네이버 symbolCode('BRK B') → 우리 티커('BRK.B')."""
    return (row.get("symbolCode") or "").strip().replace(" ", ".").upper()


def parse_us(payload: dict | None) -> dict[str, tuple[Quote, str]]:
    """티커 → (시세, 네이버 코드)."""
    out: dict[str, tuple[Quote, str]] = {}
    for row in (payload or {}).get("datas") or []:
        ticker = _symbol(row)
        if not ticker:
            continue
        session, price, pct = _session(row)
        out[ticker] = (Quote("US", ticker, price, pct, session, "USD"), row.get("reutersCode") or "")
    return out


def us_candidates(ticker: str) -> list[str]:
    """아직 네이버 코드를 모르는 티커의 후보."""
    t = ticker.upper()
    if "." in t:
        base, cls = t.split(".", 1)
        return [f"{base}{cls.lower()}", f"{base}{cls.lower()}.O"]
    return [f"{t}.O", t]


def fetch_kr(fetcher, codes: list[str]) -> dict[str, Quote]:
    out: dict[str, Quote] = {}
    for i in range(0, len(codes), _BATCH):
        chunk = codes[i:i + _BATCH]
        out.update(parse_kr(fetcher.json(WATCH_QUOTE_KR_URL.format(codes=",".join(chunk)))))
    return out


def fetch_us(fetcher, tickers: list[str], known: dict[str, str]) -> dict[str, Quote]:
    """`known` 은 티커 → 네이버 코드. 새로 알게 된 코드는 여기에 채워 넣는다."""
    wanted: list[str] = []
    for t in tickers:
        wanted.extend([known[t]] if known.get(t) else us_candidates(t))
    out: dict[str, Quote] = {}
    for i in range(0, len(wanted), _BATCH):
        chunk = wanted[i:i + _BATCH]
        got = parse_us(fetcher.json(WATCH_QUOTE_US_URL.format(codes=",".join(chunk))))
        for ticker, (quote, reuters) in got.items():
            if ticker in tickers:
                out[ticker] = quote
                if reuters:
                    known[ticker] = reuters
    return out


# --------------------------------------------------------------------------
# 급변 감지
# --------------------------------------------------------------------------


@dataclass
class Move:
    key: str
    direction: str     # "up" | "down"
    pct: float         # 창 안의 변화율(%)
    window: str        # "1분" | "5분"
    price: float
    session: str
    kind: str          # "new" 새 알림 | "extend" 같은 방향으로 더 감 | "reverse" 반대로 꺾임


class MoveDetector:
    """1분·5분 창에서 기준을 넘는 변화를 잡는다.

    * 세션이 바뀌면(프리 → 정규장) 기록을 비운다 — 시가 갭을 급변으로 잘못 잡지 않게.
    * 알린 뒤 `hold` 분 동안은 같은 방향 변화를 새 알림으로 내지 않는다. 알린 값에서
      `step`%p 더 가면 "extend"(메시지 고치기), 반대 방향 급변이면 "reverse"(새 알림).
    """

    def __init__(self, one: float = WATCH_MOVE_1M_PCT, five: float = WATCH_MOVE_5M_PCT,
                 step: float = WATCH_MOVE_STEP_PCT, hold_min: float = WATCH_INCIDENT_MIN):
        self.one, self.five, self.step = one, five, step
        self.hold = hold_min * 60
        self._hist: dict[str, deque] = {}
        self._sessions: dict[str, str] = {}
        self._last: dict[str, tuple[float, float, str]] = {}   # key → (알린 시각, 가격, 방향)

    def update(self, key: str, price: float | None, now: float, session: str) -> Move | None:
        if not price or price <= 0 or session == "closed":
            return None
        if self._sessions.get(key) != session:
            self._sessions[key] = session
            self._hist[key] = deque()
        hist = self._hist.setdefault(key, deque())
        hist.append((now, price))
        while hist and now - hist[0][0] > 330:
            hist.popleft()

        best: tuple[float, str, float] | None = None     # (기준 대비 배수, 창, 변화율)
        for window, secs, threshold in (("1분", 60, self.one), ("5분", 300, self.five)):
            ref = _reference(hist, now - secs)
            if ref is None:
                continue
            pct = (price / ref - 1) * 100
            ratio = abs(pct) / threshold
            if ratio >= 1 and (best is None or ratio > best[0]):
                best = (ratio, window, pct)
        if best is None:
            return None
        _, window, pct = best
        direction = "up" if pct > 0 else "down"

        last = self._last.get(key)
        if last and now - last[0] < self.hold:
            at, base, last_dir = last
            if direction == last_dir:
                if abs(price / base - 1) * 100 >= self.step:
                    self._last[key] = (at, price, last_dir)
                    return Move(key, direction, pct, window, price, session, "extend")
                return None
            self._last[key] = (now, price, direction)
            return Move(key, direction, pct, window, price, session, "reverse")
        self._last[key] = (now, price, direction)
        return Move(key, direction, pct, window, price, session, "new")


def _reference(hist: deque, at: float) -> float | None:
    """`at` 시각 또는 그 직전 값. 기록이 그만큼 길지 않으면 None."""
    if not hist or hist[0][0] > at:
        return None
    ref = None
    for t, p in hist:
        if t > at:
            break
        ref = p
    return ref
