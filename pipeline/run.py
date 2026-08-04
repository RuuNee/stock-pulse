"""Stock Pulse pipeline CLI.

    python -m pipeline.run doctor              # health-check data sources
    python -m pipeline.run sync                # rebuild all site data
    python -m pipeline.run sync --market KR    # one market only
    python -m pipeline.run pulse               # light macro + news refresh
    python -m pipeline.run status              # 브리핑 나갔나 / 다음은 언제인가
    python -m pipeline.run gate --market KR    # true/false: send the brief now?
    python -m pipeline.run brief --market KR --dry-run
    python -m pipeline.run brief --market KR --send
    python -m pipeline.run telegram-whoami [--token ...]
"""

from __future__ import annotations

import argparse
import sys

# Load .env for local runs (GitHub Actions injects real env vars instead).
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from .util import log


def _force_utf8_output() -> None:
    """stdout/stderr 를 UTF-8 로 고정한다.

    윈도우 기본 인코딩(cp949)은 '—' 같은 문자를 담지 못한다. 콘솔에 직접 찍을 때는
    파이썬이 UTF-16 경로를 쓰므로 티가 안 나지만, 파일이나 파이프로 넘기는 순간
    stdout 이 cp949 로 떨어지면서 UnicodeEncodeError 로 죽는다. `status > 로그.txt`
    처럼 결과를 남겨 두는 게 흔한 사용법이라 여기서 막는다.

    `util/log.py` 의 ascii 폴백은 한글을 전부 '?' 로 뭉개므로 최후 수단이다.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass   # 재설정을 지원하지 않는 스트림 — log.py 폴백에 맡긴다


def _cmd_sync(args) -> int:
    from .build import site_data
    markets = _markets(args.market)
    site_data.build(markets)
    return 0


def _cmd_pulse(args) -> int:
    from .build import site_data
    markets = _markets(args.market)
    site_data.build_pulse(markets)
    return 0


def _cmd_brief(args) -> int:
    from .build import brief as brief_mod
    from .build import site_data
    from .notify import telegram
    from .util.dates import is_trading_day, next_session_date

    markets = _markets(args.market)
    failed = []
    for market in markets:
        session = next_session_date(market)
        if not is_trading_day(market, session):
            log.info(f"{market}: {session} 휴장일 — 브리핑 생략")
            continue

        if args.rebuild:
            site = site_data.build((market,))
        else:
            site = _load_site(market)
            if site is None:
                log.warn(f"{market}: 데이터 없음 → 먼저 빌드합니다")
                site = site_data.build((market,))

        brief = brief_mod.build_brief(market, site)
        brief_mod.write_brief(brief)

        message = telegram.render(brief)
        if args.send:
            ok = telegram.send(message)
            log.ok(f"{market} 전송 {'성공' if ok else '실패'}")
            if not ok:
                failed.append(market)
        else:
            print("\n" + "=" * 50)
            print(message)
            print("=" * 50 + "\n")

    # 조용한 실패가 제일 나쁘다. 발송이 깨지면 워크플로도 빨갛게 실패시켜서
    # 다음 슬롯이 다시 시도하고(브리핑 파일이 커밋되지 않으므로) 알림도 뜬다.
    if failed:
        log.err(f"텔레그램 발송 실패: {', '.join(failed)}")
        return 1
    return 0


def _cmd_gate(args) -> int:
    """워크플로가 부르는 판정기. stdout 에는 true/false 만, 이유는 stderr 로."""
    from .gate import decide

    run, reason = decide(args.market, force=args.force)
    print(reason, file=sys.stderr)
    print("true" if run else "false")
    return 0


def _cmd_sync_gate(args) -> int:
    """data-sync 슬롯이 지금 돌 필요가 있는지. stdout 은 true/false 만."""
    from .gate import data_stale

    run, reason = data_stale(args.market)
    print(reason, file=sys.stderr)
    print("true" if run else "false")
    return 0


def _cmd_status(args) -> int:
    from .status import run as status_run
    return status_run(_markets(args.market))


def _cmd_doctor(args) -> int:
    from .doctor import run as doctor_run
    return doctor_run()


def _cmd_whoami(args) -> int:
    from .notify import telegram
    telegram.whoami(args.token)
    return 0


def _load_site(market: str) -> dict | None:
    """Assemble a minimal `site` dict from already-written JSON for brief-only runs."""
    from .config import DATA_DIR
    from .util import io
    overview = io.read_json(DATA_DIR / "market" / "overview.json")
    index = io.read_json(DATA_DIR / "tickers" / "index.json")
    news = io.read_json(DATA_DIR / "news" / "latest.json")
    if not (overview and index and news):
        return None
    return {
        "overview": overview,
        "tickers": index.get("items", []),
        "news": news.get("items", []),
    }


def _markets(value: str | None) -> tuple[str, ...]:
    if not value or value.upper() == "ALL":
        return ("KR", "US")
    return (value.upper(),)


def main(argv=None) -> int:
    _force_utf8_output()
    parser = argparse.ArgumentParser(prog="pipeline.run", description="Stock Pulse pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_sync = sub.add_parser("sync", help="rebuild all site data")
    p_sync.add_argument("--market", help="KR | US | ALL (default ALL)")
    p_sync.set_defaults(func=_cmd_sync)

    p_pulse = sub.add_parser("pulse", help="light intraday refresh (macro + news + mood)")
    p_pulse.add_argument("--market", help="KR | US | ALL (default ALL)")
    p_pulse.set_defaults(func=_cmd_pulse)

    p_brief = sub.add_parser("brief", help="build + optionally send the pre-market brief")
    p_brief.add_argument("--market", help="KR | US | ALL (default ALL)")
    p_brief.add_argument("--send", action="store_true", help="send to Telegram")
    p_brief.add_argument("--dry-run", action="store_true", help="print only (default)")
    p_brief.add_argument("--rebuild", action="store_true", help="rebuild data before briefing")
    p_brief.set_defaults(func=_cmd_brief)

    p_gate = sub.add_parser("gate", help="print true/false — should this slot send the brief?")
    p_gate.add_argument("--market", required=True, help="KR | US")
    p_gate.add_argument("--force", action="store_true", help="manual run — skip time/dup checks")
    p_gate.set_defaults(func=_cmd_gate)

    p_sgate = sub.add_parser("sync-gate",
                             help="print true/false — 이 시장 데이터를 지금 다시 만들어야 하나?")
    p_sgate.add_argument("--market", required=True, help="KR | US")
    p_sgate.set_defaults(func=_cmd_sync_gate)

    p_status = sub.add_parser("status", help="브리핑 상태 — 나갔는지, 다음은 언제인지")
    p_status.add_argument("--market", help="KR | US | ALL (default ALL)")
    p_status.set_defaults(func=_cmd_status)

    p_doc = sub.add_parser("doctor", help="check data sources")
    p_doc.set_defaults(func=_cmd_doctor)

    p_who = sub.add_parser("telegram-whoami", help="list chat_ids that messaged the bot")
    p_who.add_argument("--token", help="bot token (or set TELEGRAM_BOT_TOKEN)")
    p_who.set_defaults(func=_cmd_whoami)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        log.err("중단됨")
        return 130


if __name__ == "__main__":
    sys.exit(main())
