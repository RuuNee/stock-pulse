"""`manifest.markets[*].briefDate` 유지 규칙.

웹 브리핑 화면은 이 값을 "이번에 브리핑이 나가야 할 장" 기준으로 삼아, 들고 있는
브리핑이 그보다 오래됐으면 "아직 준비 중" 안내를 띄운다. 값이 낡으면 안내가 안 뜨고
사용자는 옛 브리핑을 최신으로 오해한다 — 2026-07-28 신고 ②가 정확히 그 모습이었다.

`build_pulse`는 종목을 다시 만들지 않으므로 `lastTradingDay`는 건드리면 안 된다.
"""

from __future__ import annotations

import json
from datetime import date

import pytest

from pipeline.build import site_data
from pipeline.util.dates import next_session_date


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(site_data, "DATA_DIR", tmp_path)
    monkeypatch.setattr(site_data.io, "DATA_DIR", tmp_path, raising=False)
    return tmp_path


def write_manifest(root, markets: dict):
    (root / "manifest.json").write_text(
        json.dumps({"version": 1, "markets": markets}), encoding="utf-8")


def read_manifest(root) -> dict:
    return json.loads((root / "manifest.json").read_text(encoding="utf-8"))


def stub_collectors(monkeypatch):
    """네트워크를 타지 않도록 pulse 의 수집 단계를 전부 비운다."""
    monkeypatch.setattr(site_data.macro_mod, "collect", lambda: [])
    monkeypatch.setattr(site_data.news_mod, "fetch_market_feeds", lambda markets: [])
    monkeypatch.setattr(site_data.link, "tag_tickers", lambda news, meta: news)
    monkeypatch.setattr(site_data.score, "enrich", lambda news: news)
    monkeypatch.setattr(site_data.mood, "score_market",
                        lambda m, idx, movers: {"score": 50, "label": "중립", "color": "amber"})


def test_pulse_refreshes_brief_date(data_dir, monkeypatch):
    stub_collectors(monkeypatch)
    write_manifest(data_dir, {
        "KR": {"lastTradingDay": "2026-07-24", "briefDate": "2026-01-01"},
        "US": {"lastTradingDay": "2026-07-24", "briefDate": "2026-01-01"},
    })

    site_data.build_pulse(("KR",))

    blocks = read_manifest(data_dir)["markets"]
    assert blocks["KR"]["briefDate"] == next_session_date("KR").isoformat()
    # 이번에 갱신하지 않은 시장은 그대로 둔다.
    assert blocks["US"]["briefDate"] == "2026-01-01"


def test_pulse_preserves_last_trading_day(data_dir, monkeypatch):
    """pulse 는 종목을 다시 만들지 않으므로 lastTradingDay 를 안다고 주장하면 안 된다."""
    stub_collectors(monkeypatch)
    write_manifest(data_dir, {"KR": {"lastTradingDay": "2026-07-24", "briefDate": "2026-01-01"}})

    site_data.build_pulse(("KR",))

    assert read_manifest(data_dir)["markets"]["KR"]["lastTradingDay"] == "2026-07-24"


def test_pulse_creates_market_block_when_missing(data_dir, monkeypatch):
    """manifest 가 비어 있던 첫 실행에서도 briefDate 는 생겨야 한다."""
    stub_collectors(monkeypatch)
    write_manifest(data_dir, {})

    site_data.build_pulse(("US",))

    block = read_manifest(data_dir)["markets"]["US"]
    assert block["briefDate"] == next_session_date("US").isoformat()
    assert block.get("lastTradingDay") is None


def test_brief_date_is_a_trading_day():
    """휴장일이 briefDate 로 나오면 웹이 영원히 '준비 중'을 띄운다."""
    for market in ("KR", "US"):
        session = next_session_date(market)
        assert isinstance(session, date)
        assert session.weekday() < 5, f"{market}: {session} 는 주말"
