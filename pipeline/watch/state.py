"""감시 서버 상태 — 재시작해도 이어지도록 JSON 한 파일에 둔다.

* seen      소스별로 이미 본 항목 id. 소스를 처음 볼 때는 있는 것을 전부 "지난 것"으로
            기록만 하고 알리지 않는다(재설치 직후 알림 폭탄 방지).
* targets   AI 가 고른 감시 대상과 고른 시각. hot 은 대상 밖에서 알림이 나 잠시 넣은 종목.
* incidents 종목별로 열려 있는 알림 — 같은 종목 소식을 한 메시지로 묶어 고쳐 쓴다.
* alerts    최근 보낸 알림 요약 — 재탕 판정과 다음 대상 선정의 재료.
* budget    오늘(KST) 쓴 Claude 비용.
* reuters   미장 티커 → 네이버 시세 코드.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..util import io
from ..util.dates import iso, parse_iso

SEEN_KEEP = 4000          # 소스마다 기억하는 id 수 (DART 하루치보다 넉넉히)
ALERTS_KEEP_HOURS = 72


class State:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        data = io.read_json(path, default={}) or {}
        self.seen: dict[str, list[str]] = data.get("seen") or {}
        self._seen_sets = {k: set(v) for k, v in self.seen.items()}
        self.targets: list[dict] = data.get("targets") or []
        self.targets_at: str | None = data.get("targetsAt")
        self.hot: list[dict] = data.get("hot") or []
        self.incidents: dict[str, dict] = data.get("incidents") or {}
        self.alerts: list[dict] = data.get("alerts") or []
        self.budget: dict = data.get("budget") or {}
        self.reuters: dict[str, str] = data.get("reuters") or {}
        self.dirty = False

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    # ---- 본 항목 ------------------------------------------------------------
    def known_source(self, source: str) -> bool:
        with self._lock:
            return source in self.seen

    def mark_seen(self, source: str, ids: list[str]) -> set[str]:
        """처음 보는 id 만 돌려주고 기록한다."""
        with self._lock:
            have = self._seen_sets.setdefault(source, set())
            order = self.seen.setdefault(source, [])
            new = {i for i in ids if i not in have}
            for i in ids:
                if i in new and i not in have:
                    have.add(i)
                    order.append(i)
            if len(order) > SEEN_KEEP:
                drop = order[:len(order) - SEEN_KEEP]
                del order[:len(drop)]
                have.difference_update(drop)
            if new:
                self.dirty = True
            return new

    # ---- 감시 대상 ----------------------------------------------------------
    def active_targets(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        with self._lock:
            out = {f"{t['market']}:{t['code']}": t for t in self.targets}
            for t in self.hot:
                until = parse_iso(t.get("until"))
                if until and until > now:
                    out.setdefault(f"{t['market']}:{t['code']}", t)
            return list(out.values())

    def set_targets(self, targets: list[dict], at: datetime) -> None:
        with self._lock:
            self.targets = targets
            self.targets_at = iso(at)
            self.dirty = True

    def add_hot(self, target: dict, hours: float, now: datetime) -> bool:
        """이미 대상이면 False."""
        key = f"{target['market']}:{target['code']}"
        with self._lock:
            if any(f"{t['market']}:{t['code']}" == key for t in self.active_targets(now)):
                return False
            self.hot = [t for t in self.hot if f"{t['market']}:{t['code']}" != key]
            self.hot.append({**target, "until": iso(now + timedelta(hours=hours))})
            self.dirty = True
            return True

    # ---- 정리·저장 ----------------------------------------------------------
    def prune(self, now: datetime, incident_min: float) -> None:
        with self._lock:
            self.hot = [t for t in self.hot
                        if (parse_iso(t.get("until")) or now) > now]
            cutoff = now - timedelta(minutes=incident_min)
            self.incidents = {k: v for k, v in self.incidents.items()
                              if (parse_iso(v.get("updatedAt")) or now) > cutoff}
            keep = now - timedelta(hours=ALERTS_KEEP_HOURS)
            self.alerts = [a for a in self.alerts if (parse_iso(a.get("at")) or now) > keep]
            self.dirty = True

    def save(self) -> None:
        with self._lock:
            payload = {
                "seen": self.seen, "targets": self.targets, "targetsAt": self.targets_at,
                "hot": self.hot, "incidents": self.incidents, "alerts": self.alerts,
                "budget": self.budget, "reuters": self.reuters,
            }
            io.write_json(self.path, payload, quiet=True)
            self.dirty = False
