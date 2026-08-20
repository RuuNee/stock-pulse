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

from ..config import telegram_chat_ids, telegram_token
from ..util import log

_API = "https://api.telegram.org/bot{token}/{method}"
_LIMIT = 3900  # under Telegram's 4096 to leave room for entities
_RECIPIENT_DELAY_SEC = 0.5  # 수신자 사이 간격. 1명이면 대기 자체가 없다
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
    # 개장 뒤에 도착한 브리핑을 아무 표시 없이 보내면 "장전"이라는 제목이 거짓말이
    # 된다. 늦었다는 사실을 맨 위에 박아 둔다 (config.BRIEF_LATE_CUTOFF).
    if brief.get("late"):
        L.append("\n⏰ <b>늦은 브리핑</b> — 스케줄러 지연으로 개장 뒤에 도착했습니다. "
                 "이미 장이 열린 상태로 읽어 주세요.")
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

    # 국장 브리핑 전용. 미장은 05:00 KST 에 닫혀서 이 기사들은 독자가 아직 못 본
    # 것들이다 — 간밤 시장 스냅샷이 지수만 보여주는 자리를 종목 단위로 메운다.
    overnight = brief.get("overnightUs", [])
    if overnight:
        L.append("\n━━━━━━━━━━━━━━")
        L.append("<b>🌏 밤사이 미국 — 종목</b>")
        for n in overnight:
            title = _e(n.get("titleKo") or n["title"])
            link = f'<a href="{_e(n["url"])}">{title}</a>' if n.get("url") else title
            tks = " · ".join(_e(t["name"]) for t in n.get("tickers", []))
            L.append(f"\n• {link}")
            if tks:
                L.append(f"   🏷 {tks}")

    chart = brief.get("chartSignals") or {}
    counts = chart.get("counts") or {}
    if counts.get("bullish") or counts.get("bearish"):
        L.append("\n━━━━━━━━━━━━━━")
        L.append("<b>📊 차트 분석 신호</b>")
        total = counts.get("bullish", 0) + counts.get("neutral", 0) + counts.get("bearish", 0)
        L.append(f"추적 {total}종목 · 매수 우위 {counts.get('bullish', 0)} · "
                 f"관망 {counts.get('neutral', 0)} · 매도 우위 {counts.get('bearish', 0)}")
        for title, rows in (("강세", chart.get("bullish", [])),
                            ("약세", chart.get("bearish", []))):
            if not rows:
                continue
            L.append(f"\n<b>{title}</b>")
            for r in rows:
                L.append(f"{_e(r.get('actionEmoji', '·'))} {_e(r['name'])} "
                         f"<b>{_e(r['actionLabel'])}</b> ({r['score']:+d}점)")
                L.append(f"   {_e(r['headline'])}")
        if chart.get("note"):
            L.append(f"\n<i>{_e(chart['note'])}</i>")

    watch = brief.get("watchlistMoves", [])
    if watch:
        L.append("\n━━━━━━━━━━━━━━")
        L.append("<b>👀 관심 종목 움직임</b>")
        for w in watch:
            note = f"  {_e(w['note'])}" if w.get("note") else ""
            sig = (f"  {_e(w.get('signalEmoji') or '·')} {_e(w['signal'])}"
                   if w.get("signal") else "")
            L.append(f"{_e(w['name'])}  {_arrow(w.get('changePct'))}{sig}{note}")

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
    """브리핑을 발송한다.

    수신자는 `TELEGRAM_CHAT_ID`(콤마 구분으로 여러 명 가능)에서 읽는다.
    `chat_id`를 넘기면 그 한 명에게만 보낸다 — 기존 호출부와 동일.
    한 명이 실패해도 나머지에게는 계속 보내고, 전원 성공일 때만 True.
    """
    token = token or telegram_token()
    targets = [chat_id] if chat_id else telegram_chat_ids()
    if not token or not targets:
        log.warn("telegram token/chat_id missing — skipping send")
        return False

    parts = _split(text)
    ok_all = True
    for i, target in enumerate(targets):
        if i:
            time.sleep(_RECIPIENT_DELAY_SEC)
        ok = True
        for part in parts:
            if not _post(token, target, part, retries):
                ok = False
        if not ok:
            ok_all = False
            log.warn(f"chat_id={target} 발송 실패 — 나머지 수신자는 계속 진행")
    if len(targets) > 1:
        log.info(f"텔레그램 수신자 {len(targets)}명")
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
            hint = _hint(exc.code, body)
            if hint:
                log.warn(f"  → {hint}")
            if exc.code == 429:
                time.sleep(2 ** attempt)
                continue
            return False
        except Exception as exc:
            log.warn(f"telegram send error: {exc}")
        time.sleep(1.5 * (attempt + 1))
    return False


def _hint(code: int, body: str) -> str | None:
    """수신자를 새로 추가할 때 실제로 자주 걸리는 실패들을 사람 말로 옮긴다."""
    low = body.lower()
    if "initiate conversation" in low:
        return "상대가 봇에게 먼저 /start 를 보내야 DM을 받을 수 있습니다."
    if "chat not found" in low:
        return "chat_id가 틀렸습니다. `python -m pipeline.run telegram-whoami` 로 확인하세요."
    if "blocked" in low:
        return "상대가 봇을 차단했습니다."
    if code == 403:
        return "봇이 이 대화에 접근할 수 없습니다(그룹에서 추방됐거나 권한 부족)."
    return None


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
    if len(seen) > 1:
        print(f"\n  여러 명에게 보내려면 그대로 붙여넣으세요:")
        print(f"  TELEGRAM_CHAT_ID={','.join(str(c) for c in seen)}")
