"""data-sync 슬롯 게이트 테스트.

2026-08-04: 국장이 15:30 KST 에 마감했는데 07:30Z 예약이 10:05Z(19:05 KST)에
깨어났다. 그 3시간 43분 동안 화면은 전날 종가를 보여줬고(LS ELECTRIC 188,400 vs
실제 마감 197,000) 사용자가 "가격이 다르다"고 신고했다.

슬롯을 여러 개 깔고 이 게이트로 거르면 먼저 깨어난 슬롯이 처리한다. 게이트가
틀리면 둘 중 하나가 난다 — 헛돌아서 26분을 태우거나, 갱신을 건너뛰어 증상이
그대로 남거나.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from pipeline.config import ET, KST
from pipeline.gate import data_stale, last_closed_session


def kst(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=KST)


@pytest.fixture
def data_dir(tmp_path):
    (tmp_path / "tickers").mkdir()
    return tmp_path


def write_index(root, rows: list[tuple[str, str]]):
    """rows = [(market, date)]"""
    items = [{"code": f"X{i}", "market": mk, "date": dt}
             for i, (mk, dt) in enumerate(rows)]
    (root / "tickers" / "index.json").write_text(
        json.dumps({"items": items}), encoding="utf-8")


# ------------------------------------------------------- last_closed_session
def test_kr_session_closes_at_1530():
    """15:29 에는 아직 오늘이 안 끝났다 — 어제가 마지막 마감 세션."""
    assert last_closed_session("KR", kst(2026, 8, 4, 15, 29)).isoformat() == "2026-08-03"
    assert last_closed_session("KR", kst(2026, 8, 4, 15, 30)).isoformat() == "2026-08-04"


def test_weekend_falls_back_to_friday():
    # 2026-08-08 은 토요일.
    assert last_closed_session("KR", kst(2026, 8, 8, 12, 0)).isoformat() == "2026-08-07"


def test_us_uses_et_clock():
    """미장은 ET 16:00 마감. 같은 UTC 라도 국장과 판정이 다르다."""
    assert last_closed_session("US", datetime(2026, 8, 4, 15, 59, tzinfo=ET)).isoformat() \
        == "2026-08-03"
    assert last_closed_session("US", datetime(2026, 8, 4, 16, 0, tzinfo=ET)).isoformat() \
        == "2026-08-04"


# -------------------------------------------------------------- data_stale
def test_stale_when_behind_the_last_close(data_dir):
    """실제 사고 재현 — 마감은 08-04 인데 데이터는 08-03."""
    write_index(data_dir, [("KR", "2026-08-03")])

    run, reason = data_stale("KR", now=kst(2026, 8, 4, 16, 0), data_dir=data_dir)

    assert run is True
    assert "2026-08-04" in reason


def test_not_stale_when_current(data_dir):
    write_index(data_dir, [("KR", "2026-08-04")])

    run, _ = data_stale("KR", now=kst(2026, 8, 4, 16, 0), data_dir=data_dir)

    assert run is False


def test_not_stale_before_close(data_dir):
    """장중에는 어제 데이터가 최신이다 — 돌 필요 없다."""
    write_index(data_dir, [("KR", "2026-08-03")])

    run, _ = data_stale("KR", now=kst(2026, 8, 4, 11, 0), data_dir=data_dir)

    assert run is False


def test_markets_are_judged_separately(data_dir):
    """국장만 뒤처졌으면 미장은 다시 만들지 않는다 — 헛일 26분을 막는 지점."""
    write_index(data_dir, [("KR", "2026-08-03"), ("US", "2026-08-03")])

    kr, _ = data_stale("KR", now=kst(2026, 8, 4, 16, 0), data_dir=data_dir)
    us, _ = data_stale("US", now=datetime(2026, 8, 4, 10, 0, tzinfo=ET), data_dir=data_dir)

    assert kr is True    # 국장은 08-04 마감이 끝났다
    assert us is False   # 미장 08-04 는 아직 진행 전 — 08-03 이 최신


def test_missing_index_builds(data_dir):
    run, reason = data_stale("KR", now=kst(2026, 8, 4, 16, 0), data_dir=data_dir)

    assert run is True
    assert "읽을 수 없" in reason


def test_market_with_no_rows_builds(data_dir):
    write_index(data_dir, [("US", "2026-08-04")])

    run, reason = data_stale("KR", now=kst(2026, 8, 4, 16, 0), data_dir=data_dir)

    assert run is True
    assert "데이터 없음" in reason
