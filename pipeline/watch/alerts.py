"""속보 알림 문구 — 첫 줄에 호재·악재를 박는다.

    🔴 호재 · 강 | 🇺🇸 엔비디아 NVDA
    📈 1분 새 +10.3% · 프리마켓 $149.56 (전일 대비 +19.1%)
    📰 [공식] NVIDIA Board Reinstates Jensen Huang as President, CEO and Board Director
       ↳ 엔비디아 이사회, 젠슨 황 CEO 복귀 결정
    🕐 발표 22:55:00 · 감지 22:55:04 (+4초)
    💬 사임 11일 만의 복귀로 리더십 불확실성 해소
    🔗 관련: SK하이닉스 · 삼성전자
    👀 CEO 사임 후속 — AI 감시 대상
    원문 보기

한국식 색: 호재·상승 빨강, 악재·하락 파랑.
"""

from __future__ import annotations

import html
import re

from ..config import KST
from ..util.dates import parse_iso

_HEAD = {"호재": "🔴", "악재": "🔵", "중립": "⚪"}
_STRENGTH = {3: "강", 2: "중", 1: "약"}
_SESSION = {"regular": "정규장", "pre": "프리마켓", "after": "애프터마켓"}
_HANGUL = re.compile(r"[가-힣]")


def _e(text) -> str:
    return html.escape(str(text), quote=False)


def _money(price: float, currency: str) -> str:
    if currency == "KRW":
        return f"{price:,.0f}원"
    return f"${price:,.2f}"


def head(inc: dict) -> str:
    verdict = inc.get("verdict") or {}
    if verdict.get("direction"):
        label = f"{_HEAD.get(verdict['direction'], '⚪')} <b>{verdict['direction']}</b>"
        strength = _STRENGTH.get(verdict.get("strength"))
        return f"{label} · {strength}" if strength and verdict["direction"] != "중립" else label
    move = inc.get("move")
    if move:
        up = move.get("direction") == "up"
        return f"{'🔺' if up else '🔻'} <b>{'급등' if up else '급락'}</b> · 원인 확인 중"
    return "⏳ <b>판정 중</b>"


def move_line(move: dict) -> str:
    up = move.get("direction") == "up"
    session = _SESSION.get(move.get("session"), "")
    price = _money(move["price"], move.get("currency", "USD"))
    day = move.get("dayPct")
    day_text = f" (전일 대비 {day:+.1f}%)" if isinstance(day, (int, float)) else ""
    return (f"{'📈' if up else '📉'} {move.get('window', '')} 새 {move['pct']:+.1f}% · "
            f"{session} {price}{day_text}").replace("  ", " ")


def quote_line(quote: dict) -> str:
    session = _SESSION.get(quote.get("session"), "")
    day = quote.get("dayPct")
    day_text = f" ({day:+.1f}%)" if isinstance(day, (int, float)) else ""
    return f"💹 지금 {session} {_money(quote['price'], quote.get('currency', 'USD'))}{day_text}"


def _clock(value) -> str:
    dt = parse_iso(value) if isinstance(value, str) else value
    return dt.astimezone(KST).strftime("%H:%M:%S") if dt else ""


def timing_line(release: dict) -> str:
    published = parse_iso(release.get("publishedAt"))
    seen = parse_iso(release.get("seenAt"))
    if not published and not seen:
        return ""
    if published and seen:
        lag = (seen - published).total_seconds()
        lag_text = f" (+{lag:.0f}초)" if 0 <= lag < 3600 else ""
        return f"🕐 발표 {_clock(published)} · 감지 {_clock(seen)}{lag_text}"
    return f"🕐 감지 {_clock(seen or published)}"


def render(inc: dict) -> str:
    verdict = inc.get("verdict") or {}
    flag = {"US": "🇺🇸", "KR": "🇰🇷"}.get(inc.get("market"), "🌐")
    code = (inc.get("code") or "") if inc.get("market") in ("KR", "US") else ""
    title = f"<b>{_e(inc.get('name') or code)}</b>" + (f" <code>{_e(code)}</code>" if code else "")
    lines = [f"{head(inc)} | {flag} {title}"]

    if inc.get("move"):
        lines.append(move_line(inc["move"]))
    elif inc.get("quote"):
        lines.append(quote_line(inc["quote"]))

    release = inc.get("release")
    if release:
        tag = "공식" if release.get("official") else _e(release.get("sourceName") or "기사")
        lines.append(f"📰 [{tag}] {_e(release.get('title', '')[:300])}")
        ko = verdict.get("title_ko")
        if ko and not _HANGUL.search(release.get("title", "")):
            lines.append(f"   ↳ {_e(ko)}")
        timing = timing_line(release)
        if timing:
            lines.append(timing)
    elif verdict.get("title_ko"):
        lines.append(f"📰 {_e(verdict['title_ko'])}")

    if verdict.get("line"):
        lines.append(f"💬 {_e(verdict['line'])}")
    if verdict.get("related"):
        lines.append("🔗 관련: " + " · ".join(_e(r) for r in verdict["related"][:3]))
    if inc.get("reason"):
        lines.append(f"👀 {_e(inc['reason'])}")
    if release and release.get("url"):
        lines.append(f'<a href="{html.escape(release["url"], quote=True)}">원문 보기</a>')
    return "\n".join(lines)


def render_targets(targets: list[dict], when: str, *, auto: bool = False) -> str:
    lines = [f"👀 <b>속보 감시 대상</b> · {_e(when)} {'자동 선정' if auto else 'AI 선정'}"]
    for market, flag in (("US", "🇺🇸"), ("KR", "🇰🇷")):
        rows = [t for t in targets if t["market"] == market]
        if not rows:
            continue
        lines.append("")
        for t in rows:
            reason = f" — {_e(t['reason'])}" if t.get("reason") else ""
            lines.append(f"{flag} <b>{_e(t.get('name') or t['code'])}</b> {_e(t['code'])}{reason}")
    lines.append("")
    lines.append("공시·보도자료는 몇 초, 시세 급변은 5초 간격으로 봅니다. 알림 첫 줄이 호재·악재입니다.")
    return "\n".join(lines)
