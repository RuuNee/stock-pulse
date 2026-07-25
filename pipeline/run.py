"""Stock Pulse pipeline CLI.

    python -m pipeline.run doctor              # health-check data sources
    python -m pipeline.run sync                # rebuild all site data
    python -m pipeline.run sync --market KR    # one market only
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
        else:
            print("\n" + "=" * 50)
            print(message)
            print("=" * 50 + "\n")
    return 0


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
