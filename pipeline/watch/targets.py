"""감시 대상 고르기 — 최근 이슈·예정 일정·급등락·연관주를 보고 Claude(Opus)가 고른다.

재료(서버에는 data/ 가 없어 GitHub 원격 파일을 읽는다 — `WATCH_DATA_BASE`)
* 최근 36시간 뉴스(data/news/latest.json) — 중요도 순 120건
* 오늘 급등락(data/tickers/index.json) — 시장마다 오르내림 상위 10개
* 미국 실적 일정(Nasdaq, collect/calendar.py) — 오늘·내일
* 최근 24시간에 보낸 속보 알림, 지난번 대상

Claude 를 못 쓰면(키 없음·상한 초과·실패) 뉴스 언급 수와 급등락으로 규칙 선정을 한다.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from ..analyze import claude
from ..config import (
    DATA_DIR,
    KST,
    WATCH_DATA_BASE,
    WATCH_DEEP_MODEL,
    WATCH_TARGET_MAX,
    WATCH_TARGET_TIMES_KST,
    all_universe,
)
from ..util import io, log
from ..util.dates import parse_iso
from .sources import norm_kr

_KINDS = ["이슈", "예정", "급등락", "연관"]

SCHEMA = {
    "type": "object",
    "properties": {"targets": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "market": {"type": "string", "enum": ["KR", "US"]},
            "code": {"type": "string"},
            "name": {"type": "string"},
            "reason": {"type": "string"},
            "kind": {"type": "string", "enum": _KINDS},
            "aliases": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["market", "code", "name", "reason", "kind", "aliases"],
        "additionalProperties": False,
    }}},
    "required": ["targets"],
    "additionalProperties": False,
}

_SYSTEM = """너는 한국 개인 투자자의 속보 감시 대상을 고르는 애널리스트다. 지금부터 다음 선정 때까지 \
(몇 시간~하루) 주가를 크게 움직일 공식 발표나 뉴스가 나올 가능성이 높은 종목을 고른다. 감시 대상이 \
되면 공시·보도자료·시세를 몇 초 간격으로 지켜보고, 소식이 뜨면 바로 호재·악재를 판정해 알린다.

고르는 기준(kind):
- 이슈: 큰 사건이 진행 중이라 후속 발표가 나올 수 있다(경영진 교체, 인수합병, 소송·조사, 규제, 리콜 등).
- 예정: 정해진 일정이 있다(실적 발표, FDA 결정, 신제품 공개, 판결, 정책 결정, 주총 등).
- 급등락: 최근 크게 움직였는데 이유가 다 안 나왔거나 이어질 수 있다.
- 연관: 위 종목 소식에 같이 움직일 종목(국장↔미장 연동 포함, 예: 엔비디아 ↔ SK하이닉스).

규칙:
- 최대 30개. 미장·국장 비율은 지금 이슈에 맞게 정한다.
- code: 미장은 티커(예: NVDA), 국장은 6자리 종목코드(예: 000660). 확실하지 않으면 빈 문자열로 두고 \
name 을 정확히 쓴다.
- reason: 왜 지켜보는지 한국어 40자 안팎. 무엇이 나오면 움직일지 구체적으로.
- aliases: 기사 제목에서 이 종목을 알아볼 이름 최대 5개(영문·한글 회사명, 핵심 인물 이름 등).
- 지난 일만 있고 이어질 소식이 없으면 뺀다. 막연한 대형주 나열은 하지 않는다."""


# --------------------------------------------------------------------------
# 언제 고르나
# --------------------------------------------------------------------------


def due(now: datetime, last: datetime | None) -> bool:
    """정해진 시각(KST)을 지났는데 그 뒤로 안 골랐거나, 마지막 선정이 10시간 넘었으면."""
    if last is None:
        return True
    if now - last > timedelta(hours=10):
        return True
    local = now.astimezone(KST)
    for hhmm in WATCH_TARGET_TIMES_KST:
        hour, minute = (int(x) for x in hhmm.split(":"))
        slot = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if last < slot <= local:
            return True
    return False


# --------------------------------------------------------------------------
# 재료
# --------------------------------------------------------------------------


def load_data(rel: str, fetcher) -> dict | None:
    """로컬 data/ 가 12시간 안에 갱신됐으면 그것을, 아니면 GitHub 원격 파일을 읽는다."""
    local = DATA_DIR / rel
    if local.exists() and time.time() - local.stat().st_mtime < 12 * 3600:
        return io.read_json(local)
    body = fetcher.get(f"{WATCH_DATA_BASE}/{rel}", fresh_only=False)
    if not body:
        return None
    try:
        return json.loads(body)
    except ValueError:
        return None


def build_context(news: dict | None, index: dict | None, earnings: list[dict],
                  alerts: list[dict], previous: list[dict], now: datetime) -> str:
    parts: list[str] = [f"지금: {now.astimezone(KST):%Y-%m-%d %H:%M} KST"]

    items = (news or {}).get("items") or []
    cutoff = now - timedelta(hours=36)
    recent = [n for n in items if (parse_iso(n.get("publishedAt")) or cutoff) > cutoff]
    recent.sort(key=lambda n: n.get("importance") or 0, reverse=True)
    lines = []
    for n in recent[:120]:
        at = parse_iso(n.get("publishedAt"))
        when = at.astimezone(KST).strftime("%m/%d %H:%M") if at else ""
        tickers = ",".join(t.get("code", "") for t in (n.get("tickers") or [])[:3])
        title = n.get("titleKo") or n.get("title") or ""
        lines.append(f"[{n.get('market', '')}] {when} {title} ({n.get('source', '')})"
                     + (f" {{{tickers}}}" if tickers else ""))
    parts.append("[최근 36시간 뉴스 — 중요도 순]\n" + ("\n".join(lines) or "(없음)"))

    rows = [r for r in (index or {}).get("items") or []
            if r.get("exchange") != "ETF" and isinstance(r.get("changePct"), (int, float))]
    for market in ("KR", "US"):
        mine = sorted((r for r in rows if r.get("market") == market),
                      key=lambda r: r["changePct"], reverse=True)
        movers = mine[:10] + mine[-10:]
        parts.append(f"[{market} 오늘 급등락]\n" + ("\n".join(
            f"{r.get('name')}({r.get('code')}) {r['changePct']:+.1f}%" for r in movers) or "(없음)"))

    parts.append("[미국 실적 발표 일정 — 오늘·내일]\n" + ("\n".join(
        f"{e['date']} {e.get('when', '')} {e.get('name')}({e.get('code')})"
        for e in earnings[:40]) or "(없음)"))
    parts.append("[최근 24시간 보낸 속보 알림]\n" + ("\n".join(
        f"{a.get('market')}:{a.get('code')} {a.get('direction', '')} {a.get('title', '')}"
        for a in alerts[-30:]) or "(없음)"))
    parts.append("[지난번 감시 대상]\n" + ("\n".join(
        f"{t['market']}:{t['code']} {t.get('name', '')} — {t.get('reason', '')}"
        for t in previous) or "(없음)"))
    return "\n\n".join(parts)


# --------------------------------------------------------------------------
# 고르기
# --------------------------------------------------------------------------


def ask(context: str) -> list[dict] | None:
    data = claude.ask_json(_SYSTEM, context, SCHEMA, model=WATCH_DEEP_MODEL, effort="medium",
                           max_tokens=12000, fallback=True, timeout=240, retries=1)
    if not data:
        return None
    return [t for t in data.get("targets") or [] if isinstance(t, dict)]


def _universe(index: dict | None) -> dict[str, dict]:
    """market:code → 종목. 설정 유니버스 별칭에 index.json 이름을 덧붙인다."""
    out: dict[str, dict] = {}
    for u in all_universe():
        if u.get("isEtf"):
            continue
        out[f"{u['market']}:{u['code']}"] = {"market": u["market"], "code": u["code"],
                                             "name": u["name"], "aliases": list(u.get("aliases") or [])}
    for r in (index or {}).get("items") or []:
        key = f"{r.get('market')}:{r.get('code')}"
        if key in out:
            extra = [r.get("name"), r.get("nameEn")]
            out[key]["aliases"] = list(dict.fromkeys(
                [*out[key]["aliases"], *[x for x in extra if x and x != out[key]["name"]]]))
    return out


def validate(raw: list[dict], index: dict | None) -> list[dict]:
    """코드를 바로잡고(국장은 이름으로 다시 찾는다), 형식이 틀린 것은 버린다."""
    uni = _universe(index)
    kr_by_name = {norm_kr(v["name"]): v for v in uni.values() if v["market"] == "KR"}
    for v in uni.values():
        if v["market"] == "KR":
            for alias in v["aliases"]:
                kr_by_name.setdefault(norm_kr(alias), v)
    out: list[dict] = []
    seen: set[str] = set()
    for t in raw:
        market = t.get("market")
        code = (t.get("code") or "").strip().upper()
        name = (t.get("name") or "").strip()
        if market == "KR":
            if f"KR:{code}" not in uni:
                hit = kr_by_name.get(norm_kr(name))
                if hit:
                    code = hit["code"]
                elif not re.fullmatch(r"\d{6}", code):
                    continue
        elif market == "US":
            if not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,6}", code):
                continue
        else:
            continue
        key = f"{market}:{code}"
        if key in seen:
            continue
        seen.add(key)
        known = uni.get(key) or {}
        aliases = [a.strip() for a in (t.get("aliases") or []) if isinstance(a, str) and a.strip()]
        out.append({
            "market": market, "code": code,
            "name": name or known.get("name") or code,
            "reason": str(t.get("reason") or "").strip()[:80],
            "kind": t.get("kind") if t.get("kind") in _KINDS else "이슈",
            "aliases": list(dict.fromkeys([*aliases, *known.get("aliases", []),
                                           *([known["name"]] if known.get("name") else [])]))[:8],
        })
    return out[:WATCH_TARGET_MAX]


def fallback(news: dict | None, index: dict | None, now: datetime) -> list[dict]:
    """Claude 없이 — 최근 24시간 뉴스에 많이 나온 종목 + 오늘 크게 움직인 종목."""
    uni = _universe(index)
    cutoff = now - timedelta(hours=24)
    counts: Counter = Counter()
    for n in (news or {}).get("items") or []:
        if (parse_iso(n.get("publishedAt")) or cutoff) <= cutoff:
            continue
        for t in n.get("tickers") or []:
            key = f"{t.get('market')}:{t.get('code')}"
            if key in uni:
                counts[key] += 1
    picked: dict[str, dict] = {}
    for market in ("KR", "US"):
        for key, count in [kc for kc in counts.most_common() if kc[0].startswith(market)][:8]:
            picked[key] = {**uni[key], "reason": f"최근 24시간 뉴스 {count}건", "kind": "이슈"}
        rows = [r for r in (index or {}).get("items") or []
                if r.get("market") == market and r.get("exchange") != "ETF"
                and isinstance(r.get("changePct"), (int, float))
                and f"{market}:{r.get('code')}" in uni]
        rows.sort(key=lambda r: abs(r["changePct"]), reverse=True)
        for r in rows[:4]:
            key = f"{market}:{r['code']}"
            picked.setdefault(key, {**uni[key], "reason": f"오늘 {r['changePct']:+.1f}%",
                                    "kind": "급등락"})
    return list(picked.values())[:WATCH_TARGET_MAX]


def select(fetcher, state, budget, now: datetime | None = None) -> tuple[list[dict], bool] | None:
    """(대상, 자동선정여부). 재료를 하나도 못 읽으면 None."""
    now = now or datetime.now(timezone.utc)
    news = load_data("news/latest.json", fetcher)
    index = load_data("tickers/index.json", fetcher)
    if not news and not index:
        log.warn("watch: 대상 선정 재료(뉴스·종목)를 못 읽었습니다 — 지난 대상을 유지합니다")
        return None
    earnings: list[dict] = []
    try:
        from ..collect.calendar import fetch_earnings
        earnings = fetch_earnings()
    except Exception as exc:
        log.warn(f"watch: 실적 일정 실패 ({exc}) — 없이 고릅니다")
    alerts = [a for a in state.alerts if (parse_iso(a.get("at")) or now) > now - timedelta(hours=24)]

    if budget.allow("targets"):
        context = build_context(news, index, earnings, alerts, state.targets, now)
        raw = ask(context)
        if raw:
            picked = validate(raw, index)
            if picked:
                log.ok(f"watch: AI 감시 대상 {len(picked)}개")
                return picked, False
        log.warn("watch: AI 대상 선정 실패 — 규칙으로 고릅니다")
    picked = fallback(news, index, now)
    log.info(f"watch: 규칙 감시 대상 {len(picked)}개")
    return picked, True
