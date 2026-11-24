"""감시 서버의 HTTP — 연결을 재사용하고, 바뀐 게 없으면 다시 읽지 않는다.

몇 초 간격으로 같은 URL 을 부르므로 두 가지가 중요하다.
1. 연결 재사용(keep-alive) — 매번 TLS 를 새로 맺으면 그만큼 늦고 서버에도 부담이다.
2. 조건부 요청 — ETag·Last-Modified 를 돌려주는 곳은 304 로 끝난다. 안 돌려주는
   곳(DART)은 본문 지문을 비교해 같으면 파싱을 건너뛴다.
"""

from __future__ import annotations

import hashlib
import json
import threading

import requests

from ..config import USER_AGENT, WATCH_HTTP_TIMEOUT
from ..util import log

_WARN_EVERY = 30   # 같은 URL 이 계속 실패하면 첫 번째와 30번마다만 경고한다


class Fetcher:
    """`get` 은 **새 본문일 때만** bytes 를 돌려준다 — 304 이거나 지난번과 같으면 None.

    requests.Session 은 스레드 안전하지 않아서 스레드마다 따로 만든다.
    """

    def __init__(self, user_agent: str = USER_AGENT, timeout: float = WATCH_HTTP_TIMEOUT):
        self._ua = user_agent
        self._timeout = timeout
        self._local = threading.local()
        self._lock = threading.Lock()
        self._validators: dict[str, tuple[str | None, str | None]] = {}
        self._digests: dict[str, str] = {}
        self._fails: dict[str, int] = {}

    def _session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update({"User-Agent": self._ua, "Accept-Encoding": "gzip, deflate"})
            self._local.session = session
        return session

    def get(self, url: str, *, fresh_only: bool = True) -> bytes | None:
        """`fresh_only=False` 면 바뀌었든 아니든 본문을 준다(시세처럼 매번 읽어야 할 때)."""
        headers: dict[str, str] = {}
        if fresh_only:
            with self._lock:
                etag, modified = self._validators.get(url, (None, None))
            if etag:
                headers["If-None-Match"] = etag
            if modified:
                headers["If-Modified-Since"] = modified
        try:
            resp = self._session().get(url, headers=headers, timeout=self._timeout)
        except requests.RequestException as exc:
            self._failed(url, type(exc).__name__)
            return None
        if resp.status_code == 304:
            self._recovered(url)
            return None
        if resp.status_code != 200:
            self._failed(url, f"HTTP {resp.status_code}")
            return None
        self._recovered(url)
        body = resp.content
        if not fresh_only:
            return body
        digest = hashlib.blake2b(body, digest_size=16).hexdigest()
        with self._lock:
            self._validators[url] = (resp.headers.get("ETag"), resp.headers.get("Last-Modified"))
            if self._digests.get(url) == digest:
                return None
            self._digests[url] = digest
        return body

    def json(self, url: str):
        body = self.get(url, fresh_only=False)
        if body is None:
            return None
        try:
            return json.loads(body)
        except ValueError:
            self._failed(url, "JSON 파싱 실패")
            return None

    def failing(self) -> dict[str, int]:
        """지금 연속으로 실패 중인 URL 과 횟수."""
        with self._lock:
            return dict(self._fails)

    def _failed(self, url: str, why: str) -> None:
        with self._lock:
            count = self._fails.get(url, 0) + 1
            self._fails[url] = count
        if count == 1 or count % _WARN_EVERY == 0:
            log.warn(f"watch: 가져오기 실패 ×{count} ({why}) {_short(url)}")

    def _recovered(self, url: str) -> None:
        with self._lock:
            count = self._fails.pop(url, 0)
        if count:
            log.info(f"watch: 다시 됩니다 (실패 {count}번 뒤) {_short(url)}")


def _short(url: str) -> str:
    return url.split("?")[0][:90]
