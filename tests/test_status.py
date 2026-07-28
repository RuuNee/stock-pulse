"""`next_send()` — "다음 브리핑은 언제 나가나".

브리핑은 하루 한 번 개장 직전 몇십 분에만 나가므로, 그 밖의 시간에는 "고장난 것"과
"아직 때가 아닌 것"이 겉보기에 같다. 이 계산이 틀리면 status 가 엉뚱한 시각을 알려
주고, 멀쩡히 대기 중인 상태를 장애로 오인하게 된다.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest

from pipeline.config import ET, KST
from pipeline.gate import next_send
from pipeline import status


def kst(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=KST)


@pytest.fixture
def empty(tmp_path):
    (tmp_path / "brief").mkdir()
    return tmp_path


def put_brief(root, name):
    (root / "brief" / name).write_text(json.dumps({"market": "KR"}), encoding="utf-8")


def test_before_todays_window_returns_today(empty):
    start, end = next_send("KR", now=kst(2026, 7, 28, 5, 0), data_dir=empty)
    assert (start.date().isoformat(), start.strftime("%H:%M")) == ("2026-07-28", "07:45")
    assert end.strftime("%H:%M") == "08:40"


def test_inside_the_window_still_returns_today(empty):
    start, _ = next_send("KR", now=kst(2026, 7, 28, 8, 0), data_dir=empty)
    assert start.date().isoformat() == "2026-07-28"


def test_after_the_window_moves_to_next_trading_day(empty):
    start, _ = next_send("KR", now=kst(2026, 7, 28, 19, 0), data_dir=empty)
    assert start.date().isoformat() == "2026-07-29"


def test_already_sent_today_moves_to_next_trading_day(empty):
    put_brief(empty, "2026-07-28-KR.json")
    start, _ = next_send("KR", now=kst(2026, 7, 28, 5, 0), data_dir=empty)
    assert start.date().isoformat() == "2026-07-29"


def test_friday_evening_skips_the_weekend(empty):
    start, _ = next_send("KR", now=kst(2026, 7, 24, 20, 0), data_dir=empty)  # 금요일 저녁
    assert start.date().isoformat() == "2026-07-27"  # 월요일


def test_skips_a_holiday(empty):
    # 2026-10-09 한글날(금) → 다음 거래일은 10-12(월)
    start, _ = next_send("KR", now=kst(2026, 10, 8, 20, 0), data_dir=empty)
    assert start.date().isoformat() == "2026-10-12"


def test_us_uses_eastern_time(empty):
    start, end = next_send("US", now=datetime(2026, 7, 28, 5, 0, tzinfo=ET), data_dir=empty)
    assert start.strftime("%H:%M") == "08:15" and end.strftime("%H:%M") == "09:10"
    assert start.tzinfo is ET


def test_report_covers_both_markets():
    lines = status.report(("KR", "US")).splitlines()
    heads = [ln for ln in lines if ln.startswith("[")]
    assert [ln[:4] for ln in heads] == ["[KR]", "[US]"]
    # 라벨은 줄머리로만 센다 — 게이트 사유 문구에도 "발송 창"이 들어간다.
    for label in ("브리핑 파일", "발송 창", "게이트", "다음 발송"):
        got = [ln for ln in lines if ln.startswith(f"  {label}")]
        assert len(got) == 2, f"{label} 가 시장마다 한 줄씩 나와야 합니다: {got}"
