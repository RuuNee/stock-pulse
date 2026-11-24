"""감시 서버 본체 — 소스 스레드들이 새 항목·급변을 큐에 넣고, 처리 스레드 하나가 판정·발송한다.

스레드
    dart · wires · newsrooms · news   RSS 를 주기마다 읽어 새 항목을 큐에 넣는다
    prices                            대상 종목 시세 → 급변이면 큐에 넣는다
    screen                            대상 밖 새 항목을 60초마다 모아 Claude 로 거른다
    targets                           정해진 시각에 감시 대상을 다시 고른다
    (메인) 처리                        큐를 우선순위대로 꺼내 판정·발송한다

우선순위: 시세 급변 > 공식 발표 > 대상 갱신·재판정 > 일반 기사.
텔레그램 발송과 상태 변경은 처리 스레드만 한다 — 같은 종목 메시지를 두 스레드가
동시에 고치지 않게.

같은 종목 소식은 `WATCH_INCIDENT_MIN` 분 동안 한 메시지(incident)로 묶는다.
* 급변 알림이 먼저 나가면("원인 확인 중") 뒤에 온 발표·기사를 원인으로 붙이고 짧은 답글을 단다.
* 발표 알림 뒤의 급변은 같은 메시지의 주가 줄만 고친다(알림음 없음).
* 반대 방향으로 크게 꺾이면 새 알림.
"""

from __future__ import annotations

import html
import itertools
import queue
import signal
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone

from ..analyze import claude
from ..config import (
    FEEDS,
    KST,
    WATCH_DART_RSS,
    WATCH_DART_SEC,
    WATCH_HOT_HOURS,
    WATCH_INCIDENT_MIN,
    WATCH_NEWS_SEC,
    WATCH_NEWSROOM_SEC,
    WATCH_NEWSROOMS,
    WATCH_PRICE_IDLE_SEC,
    WATCH_PRICE_SEC,
    WATCH_SCREEN_BATCH,
    WATCH_SCREEN_MIN_IMPACT,
    WATCH_SCREEN_SEC,
    WATCH_STATE_DIR,
    WATCH_WIRE_FEEDS,
    WATCH_WIRE_SEC,
    telegram_token,
    watch_chat_ids,
)
from ..notify import telegram
from ..util import log
from ..util.dates import iso, parse_iso
from . import alerts, judge, prices, sources
from . import targets as targets_mod
from .http import Fetcher
from .state import State

MAX_AGE_MIN = 30           # 이보다 오래된 발표는 알리지 않는다(재시작·지연 뒤 몰아치기 방지)
CAUSE_LOOKBACK_MIN = 60    # 급변 원인을 찾는 범위
TARGET_RETRY_SEC = 600     # 대상 선정 재료를 못 읽었을 때 다시 해 보는 간격
PRIO_MOVE, PRIO_OFFICIAL, PRIO_CONTROL, PRIO_NEWS = 0, 1, 2, 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _same_title(a: str, b: str) -> bool:
    norm = lambda s: "".join(ch for ch in (s or "").lower() if ch.isalnum())  # noqa: E731
    return norm(a) == norm(b)


def _release(item: dict | None) -> dict | None:
    if not item:
        return None
    meta = item.get("meta") or {}
    return {
        "title": item.get("title", ""), "url": item.get("url", ""),
        "source": item.get("source", ""), "official": bool(item.get("official")),
        "sourceName": meta.get("sourceName") or ("DART 공시" if item.get("source") == "dart" else ""),
        "publishedAt": iso(item["publishedAt"]) if item.get("publishedAt") else None,
        "seenAt": iso(item["seenAt"]) if item.get("seenAt") else None,
    }


def describe(item: dict) -> str:
    """판정 프롬프트에 넣는 한 줄."""
    meta = item.get("meta") or {}
    if item.get("source") == "dart":
        kind = f"공시({meta.get('cls', '')})"
    elif item.get("official"):
        kind = f"공식 발표({meta.get('sourceName') or item.get('source')})"
    else:
        kind = f"기사({meta.get('sourceName') or item.get('source')})"
    at = item.get("publishedAt")
    when = at.astimezone(KST).strftime("%H:%M") if at else ""
    summary = (item.get("summary") or "")[:160]
    return f"[{kind}] {when} {item.get('title', '')}" + (f" — {summary}" if summary else "")


class TelegramSender:
    """텔레그램 발송. `dry_run` 이면 콘솔에만 찍는다."""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self._fake = itertools.count(1)

    def post(self, text: str, *, silent: bool = False, reply_to: dict | None = None) -> dict:
        if self.dry_run:
            log.info(f"[dry-run] 알림{' (무음)' if silent else ''}\n{text}\n")
            return {"dry": next(self._fake)}
        return telegram.post(text, silent=silent, reply_to=reply_to)

    def edit(self, ids: dict, text: str) -> bool:
        if self.dry_run:
            log.info(f"[dry-run] 고침\n{text}\n")
            return True
        return telegram.edit(ids, text)


class Watcher:
    def __init__(self, *, dry_run: bool = False, state_path=None, fetcher=None, sender=None):
        self.state = State(state_path or (WATCH_STATE_DIR / "state.json"))
        self.fetcher = fetcher or Fetcher()
        self.sender = sender or TelegramSender(dry_run)
        self.budget = judge.Budget(self.state)
        self.detector = prices.MoveDetector()
        self.queue: queue.PriorityQueue = queue.PriorityQueue()
        self._seq = itertools.count()
        self.stop = threading.Event()
        self.recent: deque = deque(maxlen=4000)
        self.quotes: dict[str, prices.Quote] = {}
        self.screen_buf: list[dict] = []
        self.target_news: dict[str, list[dict]] = {}
        self._buf_lock = threading.Lock()
        self._next_target_try = 0.0
        self._hot_count = -1
        self.matcher = sources.Matcher([])
        self.rebuild_matcher()

    # ------------------------------------------------------------------ 공용
    def put(self, priority: int, kind: str, payload) -> None:
        self.queue.put((priority, next(self._seq), kind, payload))

    def target(self, key: str) -> dict | None:
        for t in self.state.active_targets():
            if sources.key_of(t) == key:
                return t
        return None

    def rebuild_matcher(self) -> None:
        active = self.state.active_targets()
        self.matcher = sources.Matcher(active)
        self._hot_count = len(active)

    # ------------------------------------------------------------------ 소스
    def poll_dart(self):
        body = self.fetcher.get(WATCH_DART_RSS)
        if body:
            self.ingest("dart", sources.parse_dart(body))

    def poll_wires(self):
        for key, feed in WATCH_WIRE_FEEDS.items():
            body = self.fetcher.get(feed["url"])
            if body:
                items = sources.parse_feed(body, source=key, official=True, market="US")
                for item in items:
                    item["meta"]["sourceName"] = feed["name"]
                self.ingest(key, items)

    def poll_newsrooms(self):
        for ticker, url in WATCH_NEWSROOMS.items():
            body = self.fetcher.get(url)
            if body:
                source = f"newsroom:{ticker}"
                items = sources.parse_feed(body, source=source, official=True, market="US", limit=30)
                for item in items:
                    item["meta"].update(ticker=ticker, sourceName=f"{ticker} 뉴스룸")
                self.ingest(source, items)

    def poll_news(self):
        for key, feed in FEEDS.items():
            if self.stop.is_set():
                return
            body = self.fetcher.get(feed["url"])
            if body:
                items = sources.parse_feed(body, source=key, official=False,
                                           market=feed["market"], limit=40)
                for item in items:
                    item["meta"]["sourceName"] = feed["name"]
                self.ingest(key, items)

    def ingest(self, source: str, items: list[dict]) -> None:
        if not items:
            return
        seeding = not self.state.known_source(source)
        new = self.state.mark_seen(source, [it["id"] for it in items])
        if seeding:
            log.info(f"watch: {source} 첫 확인 — 지금 있는 {len(items)}건은 지난 것으로 둡니다")
            return
        seen_at = _now()
        for item in items:
            if item["id"] in new:
                item["seenAt"] = seen_at
                self.put(PRIO_OFFICIAL if item["official"] else PRIO_NEWS, "item", item)

    def poll_prices(self) -> float:
        active = self.state.active_targets()
        got: dict[str, prices.Quote] = {}
        kr = [t["code"] for t in active if t["market"] == "KR"]
        us = [t["code"] for t in active if t["market"] == "US"]
        if kr:
            got.update({f"KR:{c}": q for c, q in prices.fetch_kr(self.fetcher, kr).items()})
        if us:
            with self.state.lock:
                known = dict(self.state.reuters)
            fetched = prices.fetch_us(self.fetcher, us, known)
            with self.state.lock:
                if known != self.state.reuters:
                    self.state.reuters.update(known)
                    self.state.dirty = True
            got.update({f"US:{c}": q for c, q in fetched.items()})
        now = time.time()
        live = False
        for key, quote in got.items():
            self.quotes[key] = quote
            if quote.session == "closed":
                continue
            live = True
            move = self.detector.update(key, quote.price, now, quote.session)
            if move:
                self.put(PRIO_MOVE, "move", (move, quote))
        return WATCH_PRICE_SEC if live else WATCH_PRICE_IDLE_SEC

    def tick_targets(self):
        if time.monotonic() < self._next_target_try:
            return
        if not targets_mod.due(_now(), parse_iso(self.state.targets_at)):
            return
        self._next_target_try = time.monotonic() + TARGET_RETRY_SEC
        result = targets_mod.select(self.fetcher, self.state, self.budget)
        if result:
            self.put(PRIO_CONTROL, "targets", result)

    # ------------------------------------------------------------------ 대상 밖 거르기
    def screen_once(self):
        with self._buf_lock:
            batch = self.screen_buf[:WATCH_SCREEN_BATCH]
            del self.screen_buf[:len(batch)]
            overflow = len(self.screen_buf) - WATCH_SCREEN_BATCH * 3
            if overflow > 0:            # 밀리면 오래된 것부터 버린다 — 늦은 속보는 속보가 아니다
                del self.screen_buf[:overflow]
                log.warn(f"watch: 선별 대기가 밀려 {overflow}건을 버렸습니다")
        if not batch or not claude.available():
            return                     # 키가 없으면 대상 밖 소식은 거를 방법이 없다(시작 때 알렸다)
        if not self.budget.allow("screen"):
            log.info(f"watch: 오늘 상한이라 {len(batch)}건 선별을 건너뜁니다")
            return
        numbered = "\n".join(f"{i + 1}. {describe(it)}" for i, it in enumerate(batch))
        rows = judge.screen(numbered, self.recent_alert_lines(hours=6))
        best: dict[str, tuple[dict, dict]] = {}
        for row in rows:
            n = row.get("n")
            if not isinstance(n, int) or not 1 <= n <= len(batch):
                continue
            if not row.get("fact") or (row.get("impact") or 0) < WATCH_SCREEN_MIN_IMPACT:
                continue
            item = batch[n - 1]
            comps = [c for c in row.get("companies") or [] if c.get("market") in ("KR", "US")]
            key = (f"{comps[0]['market']}:{comps[0].get('code') or comps[0].get('name')}"
                   if comps else f"MKT:{item['id']}")
            if key not in best or row["impact"] > best[key][1]["impact"]:
                best[key] = (item, row)
        for item, row in best.values():
            hit = self._target_of(row.get("companies") or [])
            if hit:
                self.put(PRIO_OFFICIAL, "target_item", (hit, item))
                continue
            if not self.budget.allow("confirm"):
                log.info("watch: 오늘 확인 상한 — 대상 밖 속보를 더 확인하지 않습니다")
                break
            self.budget.note_confirm()
            verdict = judge.confirm(self.confirm_context(item, row))
            if verdict and verdict.get("send"):
                self.put(PRIO_OFFICIAL, "alert", (item, verdict))

    def _target_of(self, companies: list[dict]) -> dict | None:
        for c in companies:
            t = self.target(f"{c.get('market')}:{(c.get('code') or '').upper()}")
            if t:
                return t
        return None

    def confirm_context(self, item: dict, row: dict) -> str:
        comps = ", ".join(f"{c.get('name')}({c.get('market')}:{c.get('code')})"
                          for c in row.get("companies") or [])
        lines = [f"소식: {describe(item)}", f"1차 선별: 영향 {row.get('impact')}, "
                 f"{row.get('direction')}, 관련 종목 {comps or '(시장 전체)'}"]
        if item.get("url"):
            lines.append(f"원문: {item['url']}")
        recent = self.recent_alert_lines(hours=12)
        if recent:
            lines.append(f"[이미 알린 소식]\n{recent}")
        return "\n".join(lines)

    def recent_alert_lines(self, hours: float) -> str:
        cutoff = _now() - timedelta(hours=hours)
        rows = [a for a in self.state.alerts if (parse_iso(a.get("at")) or cutoff) > cutoff]
        return "\n".join(f"- {a.get('name', '')}: {a.get('title', '')}" for a in rows[-30:])

    # ------------------------------------------------------------------ 처리
    def handle(self, kind: str, payload) -> None:
        if kind == "item":
            self.on_item(payload)
        elif kind == "move":
            self.on_move(*payload)
        elif kind == "target_item":
            target, item = payload
            self.target_news.setdefault(sources.key_of(target), []).append(item)
        elif kind == "alert":
            self.on_alert(*payload)
        elif kind == "targets":
            self.on_targets(*payload)
        elif kind == "rejudge":
            self.on_rejudge(payload)

    def on_item(self, item: dict) -> None:
        self.recent.append(item)
        published = item.get("publishedAt")
        if published and _now() - published > timedelta(minutes=MAX_AGE_MIN):
            return
        matched = self.matcher.match(item)
        if matched:
            for target in matched[:2]:
                if item["official"]:
                    self.on_release(target, item)
                else:
                    self.target_news.setdefault(sources.key_of(target), []).append(item)
            return
        if self._screenable(item):
            with self._buf_lock:
                self.screen_buf.append(item)

    @staticmethod
    def _screenable(item: dict) -> bool:
        source = item.get("source", "")
        if source == "dart":
            return sources.dart_listed(item) and \
                sources.dart_material((item.get("meta") or {}).get("report", ""))
        if source in WATCH_WIRE_FEEDS:
            return bool(sources.wire_tickers(item))
        return True

    def on_release(self, target: dict, item: dict) -> None:
        """대상 종목의 공식 발표·공시 — 가장 빠른 경로."""
        key = sources.key_of(target)
        if item.get("source") == "dart" and                 sources.dart_routine((item.get("meta") or {}).get("report", "")):
            return                       # 임원 지분 변동 같은 서식 보고 — 판정할 것도 없다
        inc = self.state.incidents.get(key)
        if inc and inc.get("release") and _same_title(inc["release"]["title"], item["title"]):
            return
        verdict = self.quick(target, [item], inc)
        if verdict is None:
            if not sources.strong_release(item):
                return
            self.deliver(target, item, None, inc, pending=True)
            return
        if not verdict["important"] or not verdict["new_fact"]:
            log.info(f"watch: {target.get('name')} 발표 — 알릴 만하지 않음: {item['title'][:60]}")
            return
        self.deliver(target, item, verdict, inc)

    def flush_target_news(self) -> None:
        """대상 종목 기사 — 종목마다 모아서 한 번에 판정한다(같은 소식 여러 매체)."""
        for key in list(self.target_news)[:3]:
            items = self.target_news.pop(key)
            target = self.target(key)
            if not target:
                continue
            items.sort(key=lambda it: FEEDS.get(it.get("source"), {}).get("weight", 0.5),
                       reverse=True)
            inc = self.state.incidents.get(key)
            verdict = self.quick(target, items[:6], inc)
            if not verdict or not verdict["important"] or not verdict["new_fact"]:
                continue
            self.deliver(target, items[0], verdict, inc)

    def deliver(self, target: dict, item: dict, verdict: dict | None, inc: dict | None,
                *, pending: bool = False) -> None:
        if inc and inc.get("move") and not inc.get("release"):
            # 급변 알림이 먼저 나갔다 — 원인을 붙이고 짧은 답글로 알린다.
            inc.update(release=_release(item), verdict=verdict, pending=pending,
                       updatedAt=iso(_now()))
            self.edit(inc)
            label = (verdict or {}).get("title_ko") or item.get("title", "")
            self.sender.post(f"{alerts.head(inc)} 원인 확인 — {html.escape(label[:120], quote=False)}",
                             silent=True, reply_to=inc.get("messages"))
            return
        inc = self.open_incident(target, release=_release(item), verdict=verdict, pending=pending)
        self.post(inc)
        if pending:
            self.put(PRIO_CONTROL, "rejudge", inc["key"])

    def on_move(self, move: prices.Move, quote: prices.Quote) -> None:
        target = self.target(move.key)
        if not target:
            return
        data = {"direction": move.direction, "pct": round(move.pct, 2), "window": move.window,
                "price": move.price, "session": move.session, "currency": quote.currency,
                "dayPct": quote.day_pct}
        inc = self.state.incidents.get(move.key)
        if inc and move.kind != "reverse":
            inc.update(move=data, updatedAt=iso(_now()))
            self.edit(inc)
            return
        cause = self.find_cause(target)
        verdict = self.quick(target, [cause], None, move=data) if cause else None
        inc = self.open_incident(target, move=data, release=_release(cause), verdict=verdict)
        self.post(inc, sound=True)

    def find_cause(self, target: dict) -> dict | None:
        matcher = sources.Matcher([target])
        cutoff = _now() - timedelta(minutes=CAUSE_LOOKBACK_MIN)
        hits = [it for it in reversed(self.recent)
                if (it.get("seenAt") or cutoff) >= cutoff and matcher.match(it)]
        hits.sort(key=lambda it: not it.get("official"))
        return hits[0] if hits else None

    def on_alert(self, item: dict, verdict: dict) -> None:
        """대상 밖 속보(Opus 확인 통과)."""
        comps = [c for c in verdict.get("companies") or [] if c.get("market") in ("KR", "US")]
        main = next((c for c in comps if (c.get("code") or "").strip()), None)
        if main:
            code = main["code"].strip().upper()
            target = {"market": main["market"], "code": code, "name": main.get("name") or code,
                      "reason": "대상 밖 속보 — 24시간 감시", "kind": "이슈",
                      "aliases": [main["name"]] if main.get("name") else []}
            if self.state.add_hot(target, WATCH_HOT_HOURS, _now()):
                self.rebuild_matcher()
            inc = self.state.incidents.get(sources.key_of(target))
            if inc and inc.get("release") and _same_title(inc["release"]["title"], item["title"]):
                return
        else:
            target = {"market": "MKT", "code": item["id"][-8:], "name": "시장 전체"}
            inc = None
        self.deliver(target, item, verdict, inc)

    def on_targets(self, picked: list[dict], auto: bool) -> None:
        self.state.set_targets(picked, _now())
        self.rebuild_matcher()
        when = _now().astimezone(KST).strftime("%m/%d %H:%M")
        self.sender.post(alerts.render_targets(picked, when, auto=auto), silent=True)

    def on_rejudge(self, key: str) -> None:
        inc = self.state.incidents.get(key)
        if not inc or not inc.get("pending") or not self.budget.allow("quick"):
            return
        target = self.target(key) or inc
        release = inc.get("release") or {}
        item = {"title": release.get("title", ""), "summary": "", "source": release.get("source"),
                "official": release.get("official"), "meta": {"sourceName": release.get("sourceName")},
                "publishedAt": parse_iso(release.get("publishedAt"))}
        verdict = judge.quick(self.quick_context(target, [item], None, inc.get("move")), timeout=25)
        if verdict:
            inc.update(verdict=verdict, pending=False, updatedAt=iso(_now()))
            self.edit(inc)

    # ------------------------------------------------------------------ 판정·발송
    def quick(self, target: dict, items: list[dict], inc: dict | None,
              move: dict | None = None) -> dict | None:
        if not self.budget.allow("quick"):
            return None
        started = time.monotonic()
        verdict = judge.quick(self.quick_context(target, items, inc, move))
        log.info(f"watch: 즉시 판정 {target.get('name')} → "
                 f"{verdict['direction'] if verdict else '실패'} ({time.monotonic() - started:.1f}초)")
        return verdict

    def quick_context(self, target: dict, items: list[dict], inc: dict | None,
                      move: dict | None) -> str:
        lines = [f"회사: {target.get('name')} ({target.get('market')}:{target.get('code')})"]
        if target.get("reason"):
            lines.append(f"감시 이유: {target['reason']}")
        main = items[0]
        lines.append(f"소식: {describe(main)}")
        if main.get("publishedAt"):
            lines.append(f"발표 시각: {main['publishedAt'].astimezone(KST):%H:%M:%S} KST")
        if len(items) > 1:
            lines.append("같은 종목 다른 기사:\n" + "\n".join(f"- {describe(it)}" for it in items[1:6]))
        quote = self.quotes.get(sources.key_of(target)) if target.get("market") in ("KR", "US") else None
        if move:
            lines.append(f"주가: {move['window']} 새 {move['pct']:+.1f}% "
                         f"({move['session']}, 당일 {move.get('dayPct')}%)")
        elif quote and quote.session != "closed" and quote.price:
            lines.append(f"현재 주가: {quote.session} {quote.price} (당일 {quote.day_pct}%)")
        told = []
        if inc and inc.get("verdict"):
            told.append(inc["verdict"].get("title_ko") or "")
        elif inc and inc.get("release"):
            told.append(inc["release"].get("title", ""))
        key = sources.key_of(target)
        cutoff = _now() - timedelta(hours=24)
        told += [a.get("title", "") for a in self.state.alerts
                 if f"{a.get('market')}:{a.get('code')}" == key
                 and (parse_iso(a.get("at")) or cutoff) > cutoff]
        told = [t for t in dict.fromkeys(told) if t]
        lines.append("이미 알린 내용: " + (" / ".join(told[-5:]) if told else "(없음)"))
        return "\n".join(lines)

    def open_incident(self, target: dict, **fields) -> dict:
        key = sources.key_of(target)
        quote = self.quotes.get(key)
        now = iso(_now())
        reason = target.get("reason")
        inc = {
            "key": key, "market": target["market"], "code": target.get("code", ""),
            "name": target.get("name") or target.get("code", ""),
            "reason": f"{reason} — 감시 대상" if reason and target["market"] in ("KR", "US") else None,
            "openedAt": now, "updatedAt": now, "messages": {},
            "verdict": None, "pending": False, "release": None, "move": None,
            "quote": ({"price": quote.price, "dayPct": quote.day_pct, "session": quote.session,
                       "currency": quote.currency}
                      if quote and quote.session != "closed" and quote.price else None),
        }
        inc.update(fields)
        return inc

    def post(self, inc: dict, *, sound: bool = False) -> None:
        verdict = inc.get("verdict") or {}
        silent = not sound and verdict.get("strength") == 1
        inc["messages"] = self.sender.post(alerts.render(inc), silent=silent)
        with self.state.lock:
            self.state.incidents[inc["key"]] = inc
            self.state.alerts.append({
                "at": iso(_now()), "market": inc["market"], "code": inc.get("code"),
                "name": inc.get("name"), "direction": verdict.get("direction") or
                ("급등" if (inc.get("move") or {}).get("direction") == "up" else
                 "급락" if inc.get("move") else ""),
                "title": verdict.get("title_ko") or (inc.get("release") or {}).get("title", ""),
            })
            self.state.dirty = True

    def edit(self, inc: dict) -> None:
        if inc.get("messages"):
            self.sender.edit(inc["messages"], alerts.render(inc))
        with self.state.lock:
            self.state.incidents[inc["key"]] = inc
            self.state.dirty = True

    # ------------------------------------------------------------------ 돌리기
    def housekeeping(self) -> None:
        self.state.prune(_now(), WATCH_INCIDENT_MIN)
        if len(self.state.active_targets()) != self._hot_count:
            self.rebuild_matcher()
        self.budget.sync()
        if self.state.dirty:
            self.state.save()

    def _loop(self, name: str, fn, every: float):
        while not self.stop.is_set():
            try:
                wait = fn()
            except Exception as exc:          # 한 소스가 죽어도 나머지는 계속 돈다
                log.warn(f"watch[{name}] 오류: {exc}\n{traceback.format_exc(limit=3)}")
                wait = None
            self.stop.wait(wait if isinstance(wait, (int, float)) else every)

    def process_forever(self) -> None:
        last_flush = last_house = time.monotonic()
        while not self.stop.is_set():
            try:
                _, _, kind, payload = self.queue.get(timeout=0.5)
            except queue.Empty:
                kind = None
            if kind:
                try:
                    self.handle(kind, payload)
                except Exception as exc:
                    log.warn(f"watch: 처리 오류 ({kind}): {exc}\n{traceback.format_exc(limit=4)}")
            now = time.monotonic()
            if now - last_flush >= 8:
                last_flush = now
                try:
                    self.flush_target_news()
                except Exception as exc:
                    log.warn(f"watch: 대상 기사 판정 오류: {exc}")
            if now - last_house >= 15:
                last_house = now
                try:
                    self.housekeeping()
                except Exception as exc:
                    log.warn(f"watch: 정리 오류: {exc}")

    def run(self) -> int:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, lambda *_: self.stop.set())
            except (ValueError, OSError):
                pass
        log.step("속보 감시 시작")
        log.info(f"  Claude: {'켜짐' if claude.available() else '없음 — 규칙 알림만'} · "
                 f"텔레그램 수신자 {len(watch_chat_ids())}명 · 상태 {self.state.path}")
        loops = [
            ("dart", self.poll_dart, WATCH_DART_SEC),
            ("wires", self.poll_wires, WATCH_WIRE_SEC),
            ("newsrooms", self.poll_newsrooms, WATCH_NEWSROOM_SEC),
            ("news", self.poll_news, WATCH_NEWS_SEC),
            ("prices", self.poll_prices, 5),
            ("screen", self.screen_once, WATCH_SCREEN_SEC),
            ("targets", self.tick_targets, 30),
        ]
        for name, fn, every in loops:
            threading.Thread(target=self._loop, args=(name, fn, every),
                             name=f"watch-{name}", daemon=True).start()
        self.process_forever()
        self.state.save()
        log.info(f"속보 감시 끝 · {claude.stats()}")
        return 0


# --------------------------------------------------------------------------
# 점검 — 서버에 깔고 나서 소스가 다 살아 있는지 한 번 본다 (`watch --once`)
# --------------------------------------------------------------------------


def smoke(fetcher: Fetcher | None = None) -> int:
    fetcher = fetcher or Fetcher()
    ok = True

    def report(name: str, items: list[dict] | None):
        nonlocal ok
        if not items:
            log.warn(f"  ✗ {name}: 못 읽음")
            return False
        newest = max((it["publishedAt"] for it in items if it.get("publishedAt")), default=None)
        when = newest.astimezone(KST).strftime("%m/%d %H:%M") if newest else "시각 없음"
        log.ok(f"  {name}: {len(items)}건, 최신 {when} — {items[0]['title'][:50]}")
        return True

    log.step("속보 감시 점검")
    body = fetcher.get(WATCH_DART_RSS, fresh_only=False)
    ok &= report("DART 공시", sources.parse_dart(body) if body else None)
    for key, feed in WATCH_WIRE_FEEDS.items():
        body = fetcher.get(feed["url"], fresh_only=False)
        report(feed["name"], sources.parse_feed(body, source=key, official=True) if body else None)
    for ticker, url in WATCH_NEWSROOMS.items():
        body = fetcher.get(url, fresh_only=False)
        report(f"{ticker} 뉴스룸", sources.parse_feed(body, source=ticker, official=True) if body else None)
    live = sum(1 for feed in FEEDS.values() if fetcher.get(feed["url"], fresh_only=False))
    log.info(f"  일반 뉴스 피드: {live}/{len(FEEDS)} 살아 있음")

    kr = prices.fetch_kr(fetcher, ["005930", "000660"])
    us = prices.fetch_us(fetcher, ["NVDA", "XOM"], {})
    for key, q in [*kr.items(), *us.items()]:
        log.ok(f"  시세 {key}: {q.price} ({q.session}, 당일 {q.day_pct}%)")
    if len(kr) < 2 or len(us) < 2:
        log.warn("  ✗ 시세: 일부 종목을 못 받았습니다")
        ok = False

    log.info(f"  Claude: {'켜짐' if claude.available() else '없음 — 규칙 알림만'}")
    log.info(f"  텔레그램: 토큰 {'있음' if telegram_token() else '없음'}, "
             f"수신자 {len(watch_chat_ids())}명")
    return 0 if ok else 1
