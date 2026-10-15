"""Telegram delivery of the pre-market brief (md파일/04-알림과스케줄.md §2).

HTML parse mode, Korean-style up=red/down=blue emoji, a one-line "왜 중요한가"
per news item (when the LLM wrote one), and automatic splitting at Telegram's
4096-char limit.
"""

from __future__ import annotations

import html
import time
from datetime import date
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
    """브리핑 → 텔레그램 HTML.

    순서는 "읽을 이유가 큰 것부터": 오늘 장 전망 → 3가지 → 해설 → 지표 → 뉴스 →
    일정. 2026-10-15 개편에서 뺀 것: 3줄 요약에 섞이던 차트 신호 줄, 뉴스마다 붙던
    키워드 규칙 💡(엉뚱한 기사에 붙었다), "밤사이 미국" 별도 블록(국내 뉴스와 같은
    후보에서 고른다), 관심 종목 블록(사이트에만 남긴다). 차트 신호는 한 줄로 줄였다.
    """
    market = brief["market"]
    label = "📈 국장 장전 브리핑" if market == "KR" else "🌙 미장 장전 브리핑"
    mood = brief.get("mood", {})
    dot = {"green": "🟢", "amber": "🟡", "red": "🔴"}.get(mood.get("color"), "⚪")

    L: list[str] = []
    L.append(f"<b>{label}</b>")
    L.append(_e(_date_label(brief["date"])))
    # 개장 뒤에 도착한 브리핑을 아무 표시 없이 보내면 "장전"이라는 제목이 거짓말이
    # 된다. 늦었다는 사실을 맨 위에 박아 둔다 (config.BRIEF_LATE_CUTOFF).
    if brief.get("late"):
        L.append("\n⏰ <b>늦은 브리핑</b> — 스케줄러 지연으로 개장 뒤에 도착했습니다. "
                 "이미 장이 열린 상태로 읽어 주세요.")
    if mood.get("label"):
        # 예전 파일(kind 없음)은 전날 기준 분위기였다 — 같은 말로 부르지 않는다.
        title = "오늘 장 전망" if mood.get("kind") == "outlook" else "오늘 시장 분위기"
        L.append(f"\n{dot} {title}: <b>{_e(mood['label'])}</b> ({mood.get('score', '?')}점)")
        if mood.get("reason"):
            L.append(f"<i>{_e(mood['reason'])}</i>")

    if brief.get("headline"):
        L.append(f"\n<b>{_e(brief['headline'])}</b>")

    L.append(_RULE)
    L.append("<b>📌 오늘 꼭 알아야 할 3가지</b>")
    for i, line in enumerate(brief.get("threeLines", []), 1):
        L.append(f"{i}. {_e(line)}")

    analysis = brief.get("analysis") or []
    if analysis:
        L.append(_RULE)
        L.append("<b>🧭 시장 해설</b>")
        for sec in analysis:
            L.append(f"\n<b>▸ {_e(sec.get('title', ''))}</b>")
            L.append(_e(sec.get("body", "")))
    elif brief.get("wrapHeadlines"):
        # 해설을 못 만든 날(LLM 실패)에도 "왜"의 실마리는 남긴다 — 시황 기사 제목.
        L.append(_RULE)
        L.append("<b>🧭 시황 기사</b>")
        for w in brief["wrapHeadlines"][:3]:
            title = _e(w["title"])
            link = f'<a href="{_e(w["url"])}">{title}</a>' if w.get("url") else title
            src = f" · {_e(w['source'])}" if w.get("source") else ""
            L.append(f"• {link}{src}")

    snap = brief.get("marketSnapshot", [])
    if snap:
        L.append(_RULE)
        L.append("<b>📊 지표</b>")
        for s in snap:
            L.append(_snapshot_line(s))
        flows = (brief.get("flows") or {}).get("KOSPI")
        if flows:
            L.append(f"수급(코스피 {flows['date'][5:]}): 외국인 {_eok(flows['foreign'])} · "
                     f"기관 {_eok(flows['institution'])} · 개인 {_eok(flows['individual'])}")

    news = brief.get("topNews", [])
    if news:
        L.append(_RULE)
        L.append("<b>📰 주요 뉴스</b>")
        for i, n in enumerate(news, 1):
            title = _e(n.get("titleKo") or n["title"])
            link = f'<a href="{_e(n["url"])}">{title}</a>' if n.get("url") else title
            src = f" · {_e(n['source'])}" if n.get("source") else ""
            L.append(f"\n{i}. {link}{src}")
            if n.get("why"):
                L.append(f"   💡 {_e(n['why'])}")

    # 브리핑에서 유일하게 앞을 보는 블록. 국장 브리핑에는 그날 밤 미국장 일정이 실린다.
    cal = brief.get("calendar", [])
    if cal:
        L.append(_RULE)
        L.append("<b>📅 오늘 밤 미국 실적</b>" if market == "KR" else "<b>📅 오늘 예정</b>")
        for c in cal:
            star = "⭐ " if c.get("importance") == "high" else ""
            eps = f" · EPS 전망 {_e(c['epsForecast'])}" if c.get("epsForecast") else ""
            L.append(f"{star}{_e(c['title'])} · {_e(c.get('time', '시간 미정'))}{eps}")

    chart = brief.get("chartSignals") or {}
    counts = chart.get("counts") or {}
    if counts.get("bullish") or counts.get("bearish"):
        ups = "·".join(_e(r["name"]) for r in chart.get("bullish", [])[:2])
        downs = "·".join(_e(r["name"]) for r in chart.get("bearish", [])[:2])
        names = " — ".join(x for x in (f"강세 {ups}" if ups else "",
                                        f"약세 {downs}" if downs else "") if x)
        L.append(f"\n📈 차트 신호(지표만 본 기계적 판정): 매수 우위 {counts.get('bullish', 0)} · "
                 f"매도 우위 {counts.get('bearish', 0)}" + (f"\n   {names}" if names else ""))

    if brief.get("siteUrl"):
        L.append(f"\n🔗 <a href=\"{_e(brief['siteUrl'])}\">자세히 보기</a>")
    L.append(f"\nℹ️ {_e(brief['disclaimer'])}")
    return "\n".join(L)


_RULE = "\n━━━━━━━━━━━━━━"


def _date_label(day: str) -> str:
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return day
    return f"{d.isoformat()} ({'월화수목금토일'[d.weekday()]})"


def _snapshot_line(s: dict) -> str:
    v = s.get("value")
    if s.get("unit") == "%":
        # 금리는 % 변화율이 아니라 bp(0.01%p)로 읽는다. "-0.52%" 는 금리가 0.52%p
        # 내렸다는 말로 오해된다 — 실제로는 0.03%p 였다.
        val = f"{v:.2f}%" if isinstance(v, (int, float)) else "-"
        chg = s.get("change")
        move = (f"{_UP if chg >= 0 else _DOWN} {chg * 100:+.0f}bp"
                if isinstance(chg, (int, float)) else _arrow(s.get("changePct")))
        return f"{_e(s['name'])}  {val}  {move}"
    val = f"{v:,.2f}" if isinstance(v, (int, float)) else "-"
    return f"{_e(s['name'])}  {val}  {_arrow(s.get('changePct'))}"


def _eok(value: int) -> str:
    from ..collect.flows import eok_label
    return _e(eok_label(value))


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
