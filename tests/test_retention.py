"""데이터 보관 정리 테스트.

날짜별 브리핑 파일은 시장당 하루 1개씩 영원히 쌓인다. 정리 자체보다 위험한
건 "너무 많이 지우는 것"이다 — 이번 세션 파일이 사라지면 게이트의 중복 발송
방지가 풀려서 브리핑이 두 번 나간다. 그래서 경계와 비대상 파일을 고정한다.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from pipeline.build.brief import prune_briefs
from pipeline.config import BRIEF_KEEP_DAYS
from pipeline.gate import brief_path, decide


TODAY = date(2026, 8, 3)


@pytest.fixture
def brief_dir(tmp_path):
    (tmp_path / "brief").mkdir()
    return tmp_path


def touch(root, day: date, market: str):
    path = root / "brief" / f"{day.isoformat()}-{market}.json"
    path.write_text(json.dumps({"market": market, "date": day.isoformat()}), "utf-8")
    return path


def test_keeps_recent_deletes_old(brief_dir):
    keep = touch(brief_dir, TODAY - timedelta(days=BRIEF_KEEP_DAYS - 1), "KR")
    drop = touch(brief_dir, TODAY - timedelta(days=BRIEF_KEEP_DAYS + 1), "KR")

    removed = prune_briefs("KR", data_dir=brief_dir, today=TODAY)

    assert removed == [drop]
    assert keep.exists() and not drop.exists()


def test_cutoff_day_itself_survives(brief_dir):
    """정확히 BRIEF_KEEP_DAYS 일 전은 남긴다 — 경계에서 하루 더 지우지 않는다."""
    edge = touch(brief_dir, TODAY - timedelta(days=BRIEF_KEEP_DAYS), "KR")

    prune_briefs("KR", data_dir=brief_dir, today=TODAY)

    assert edge.exists()


def test_todays_file_survives(brief_dir):
    """게이트가 중복 발송을 막는 근거라, 오늘 파일은 어떤 경우에도 남아야 한다."""
    today_file = touch(brief_dir, TODAY, "KR")

    prune_briefs("KR", data_dir=brief_dir, today=TODAY)

    assert today_file.exists()


def test_other_market_untouched(brief_dir):
    """KR 정리가 US 파일을 건드리면 미장 브리핑이 중복 발송된다."""
    us_old = touch(brief_dir, TODAY - timedelta(days=BRIEF_KEEP_DAYS + 5), "US")

    prune_briefs("KR", data_dir=brief_dir, today=TODAY)

    assert us_old.exists()


def test_latest_pointer_untouched(brief_dir):
    """`latest-KR.json` 은 사이트가 읽는 유일한 브리핑 파일이다."""
    latest = brief_dir / "brief" / "latest-KR.json"
    latest.write_text("{}", "utf-8")

    prune_briefs("KR", data_dir=brief_dir, today=TODAY)

    assert latest.exists()


def test_gate_still_blocks_after_prune(brief_dir):
    """정리 후에도 중복 발송 방지가 살아 있는지 게이트로 직접 확인한다."""
    from datetime import datetime

    from pipeline.config import KST

    now = datetime(2026, 8, 3, 8, 20, tzinfo=KST)
    session = brief_path("KR", date(2026, 8, 3), brief_dir)
    session.write_text("{}", "utf-8")
    touch(brief_dir, TODAY - timedelta(days=BRIEF_KEEP_DAYS + 1), "KR")

    prune_briefs("KR", data_dir=brief_dir, today=TODAY)
    run, reason = decide("KR", now=now, data_dir=brief_dir)

    assert run is False
    assert "중복" in reason
