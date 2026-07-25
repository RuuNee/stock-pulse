"""Telegram delivery of the pre-market brief (md파일/04-알림과스케줄.md §2).

HTML parse mode, Korean-style up=red/down=blue emoji, a one-line "왜 중요한가"
per news item, and automatic splitting at Telegram's 4096-char limit.
"""

from __future__ import annotations

import html
import time
import urllib.error
import urllib.parse
import urllib.request

from ..config import telegram_chat_id, telegram_token
from ..util import log

_API = "https://api.telegram.org/bot{token}/{method}"
_LIMIT = 3900  # under Telegram's 4096 to leave room for entities
_UP, _DOWN = "🔴", "🔵"  # 한국식: 상승 빨강 / 하락 파랑


def _e(text: str) -> str:
    return html.escape(str(text), quote=False)


def _arrow(pct) -> str:
    if pct is None:
        return ""
    sign = "+" if pct >= 0 else ""
    return f"{_UP if pct >= 0 else _DOWN} {sign}{pct:.2f}%"


def render(brief: dict) -> str:
    label = "📈 국장 장전 브리핑" if brief["market"] == "KR" else "🌙 미장 장전 브리핑"
    mood = brief.get("mood", {})
    dot = {"green": "🟢", "amber": "🟡", "red": "🔴"}.get(mood.get("color"), "⚪")

    L: list[str] = []
    L.append(f"<b>{label}</b>")
    L.append(f"{_e(brief['date'])}")
    if mood.get("label"):
        L.append(f"\n{dot} 오늘 시장 분위기: <b>{_e(mood['label'])}</b> ({mood.get('score', '?')}점)")

    if brief.get("headline"):
        L.append(f"\n<i>{_e(brief['headline'])}</i>")

    L.append("\n━━━━━━━━━━━━━━")
    L.append("<b>📌 오늘 꼭 알아야 할 3가지</b>")
    for i, line in enumerate(brief.get("threeLines", []), 1):
        L.append(f"{i}. {_e(line)}")

    snap = brief.get("marketSnapshot", [])
    if snap:
        L.append("\n━━━━━━━━━━━━━━")
        L.append("<b>📊 간밤 시장</b>")
        for s in snap:
            val = f"{s['value']:,.2f}" if isinstance(s.get("value"), (int, float)) else "-"
            L.append(f"{_e(s['name'])}  {val}  {_arrow(s.get('changePct'))}")

    news = brief.get("topNews", [])
    if news:
        L.append("\n━━━━━━━━━━━━━━")
        L.append("<b>📰 주요 뉴스</b>")
        for i, n in enumerate(news, 1):
            title = _e(n.get("titleKo") or n["title"])
            link = f'<a href="{_e(n["url"])}">{title}</a>' if n.get("url") else title
            L.append(f"\n{i}. {link}")
            if n.get("why"):
                L.append(f"   💡 {_e(n['why'])}")
            tks = " · ".join(_e(t["name"]) for t in n.get("tickers", []))
            src = _e(n.get("source", ""))
            meta = " · ".join(x for x in (tks, src) if x)
            if meta:
                L.append(f"   🏷 {meta}")

    watch = brief.get("watchlistMoves", [])
    if watch:
        L.append("\n━━━━━━━━━━━━━━")
        L.append("<b>👀 관심 종목 움직임</b>")
        for w in watch:
            note = f"  {_e(w['note'])}" if w.get("note") else ""
            L.append(f"{_e(w['name'])}  {_arrow(w.get('changePct'))}{note}")

    if brief.get("siteUrl"):
        L.append(f"\n🔗 <a href=\"{_e(brief['siteUrl'])}\">자세히 보기</a>")
    L.append(f"\nℹ️ {_e(brief['disclaimer'])}")
    return "\n".join(L)


def _split(text: str) -> list[str]:
    if len(text) <= _LIMIT:
        return [text]
    chunks, cur = [], []
    size = 0
    for line in text.split("\n"):
        if size + len(line) + 1 > _LIMIT and cur:
            chunks.append("\n".join(cur))
            cur, size = [], 0
        cur.append(line)
        size += len(line) + 1
    if cur:
        chunks.append("\n".join(cur))
    return chunks


def send(text: str, *, token: str | None = None, chat_id: str | None = None,
         retries: int = 3) -> bool:
    token = token or telegram_token()
    chat_id = chat_id or telegram_chat_id()
    if not token or not chat_id:
        log.warn("telegram token/chat_id missing — skipping send")
        return False

    ok_all = True
    for part in _split(text):
        if not _post(token, chat_id, part, retries):
            ok_all = False
    return ok_all


def _post(token: str, chat_id: str, text: str, retries: int) -> bool:
    url = _API.format(token=token, method="sendMessage")
    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": "true",
    }).encode()

    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=payload)
            with urllib.request.urlopen(req, timeout=20) as resp:
                if resp.status == 200:
                    return True
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:200]
            log.warn(f"telegram HTTP {exc.code}: {body}")
            if exc.code == 429:
                time.sleep(2 ** attempt)
                continue
            return False
        except Exception as exc:
            log.warn(f"telegram send error: {exc}")
        time.sleep(1.5 * (attempt + 1))
    return False


def whoami(token: str | None = None) -> None:
    """Print chat IDs that have messaged the bot (setup helper)."""
    token = token or telegram_token()
    if not token:
        log.err("no token — pass --token or set TELEGRAM_BOT_TOKEN")
        return
    url = _API.format(token=token, method="getUpdates")
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            import json
            data = json.loads(resp.read())
    except Exception as exc:
        log.err(f"getUpdates failed: {exc}")
        return

    seen = {}
    for upd in data.get("result", []):
        msg = upd.get("message") or upd.get("channel_post") or {}
        chat = msg.get("chat", {})
        if chat.get("id"):
            seen[chat["id"]] = chat.get("title") or chat.get("username") or chat.get("first_name")
    if not seen:
        log.warn("대화가 없습니다. 봇에게 아무 메시지나 먼저 보내세요.")
        return
    log.ok("찾은 chat_id:")
    for cid, name in seen.items():
        print(f"  chat_id={cid}  ({name})")
