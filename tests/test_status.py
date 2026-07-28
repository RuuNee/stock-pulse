"""`next_send()` — "다음 브리핑은 언제 나가나".

브리핑은 하루 한 번 개장 직전 몇십 분에만 나가므로, 그 밖의 시간에는 "고장난 것"과
"아직 때가 아닌 것"이 겉보기에 같다. 이 계산이 틀리면 status 가 엉뚱한 시각을 알려
주고, 멀쩡히 대기 중인 상태를 장애로 오인하게 된다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta

import pytest

from pipeline.config import ET, KST, ROOT
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


# --------------------------------------------------------------------------
# 로컬 트리가 낡았을 때의 경고
# --------------------------------------------------------------------------
@pytest.mark.parametrize("behind", [0, None])
def test_no_warning_when_up_to_date(behind):
    assert status.lag_lines(behind, timedelta(hours=3)) == []


def test_warns_with_commit_count_and_fetch_age():
    head, detail, blank = status.lag_lines(4, timedelta(hours=6))
    assert "4커밋 뒤" in head and "6시간 전" in head
    assert "git pull" in detail   # 무엇을 하라는지 없으면 경고가 쓸모없다
    assert blank == ""


def test_warns_without_fetch_age_when_never_fetched():
    head, _, _ = status.lag_lines(2, None)
    assert "2커밋 뒤" in head and "fetch" not in head


@pytest.mark.parametrize("delta,expected", [
    (timedelta(minutes=0), "0분 전"),
    (timedelta(minutes=59), "59분 전"),
    (timedelta(minutes=60), "1시간 전"),
    (timedelta(hours=23, minutes=59), "23시간 전"),
    (timedelta(days=3), "3일 전"),
    (timedelta(seconds=-30), "0분 전"),   # 시계가 뒤로 튀어도 음수는 안 찍는다
])
def test_ago_wording(delta, expected):
    assert status._ago(delta) == expected


def test_status_survives_a_cp949_stdout():
    """리다이렉트하면 stdout 이 윈도우 기본 인코딩으로 떨어진다.

    리포트에는 '—' 가 늘 들어가는데 cp949 로는 못 담는다. 예전에는 여기서
    UnicodeEncodeError 로 죽어서, "왜 브리핑이 안 왔지"를 보려고 만든 명령이
    정작 결과를 파일로 남기려는 순간 못 쓰게 됐다.
    """
    done = subprocess.run(
        [sys.executable, "-m", "pipeline.run", "status"],
        cwd=ROOT, capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "cp949"},
    )
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    assert "—" in done.stdout.decode("utf-8")
