"""`.github/scripts/kick-briefs.sh` — 깬 김에 장전 브리핑을 불러 주는 스크립트.

이 스크립트는 덤이라 무슨 일이 있어도 exit 0 이다. 그래서 망가져도 워크플로가 초록색
그대로 조용히 안 부른다 — 2026-11-03 처럼 브리핑 슬롯이 안 깨는 날에야 드러난다.
여기서 `python3`(게이트)와 `gh` 를 셸 함수로 바꿔 끼우고 실제로 돌려 본다.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ".github/scripts/kick-briefs.sh"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash 가 없습니다")


def kick(*markets: str, modes: dict[str, str], busy: str = "0",
         list_fails: bool = False) -> list[str]:
    """스크립트를 돌리고, 부른 `gh workflow run` 명령만 돌려준다."""
    gate = " ".join(f'*"--market {m}"*) printf \'%s\\n\' false {mode} 0 ;;'
                    for m, mode in modes.items())
    listing = "return 1" if list_fails else f"echo {busy}"
    stubs = f"""
python3() {{ case "$*" in {gate} esac; }}
gh() {{
  case "$1 $2" in
    "run list") {listing} ;;
    "workflow run") echo "DISPATCH $*" ;;
  esac
}}
"""
    done = subprocess.run([BASH, "-c", stubs + f"source {SCRIPT} {' '.join(markets)}"],
                          cwd=ROOT, capture_output=True, encoding="utf-8", errors="replace",
                          timeout=60)
    assert done.returncode == 0, done.stderr
    return [line.removeprefix("DISPATCH ") for line in done.stdout.splitlines()
            if line.startswith("DISPATCH ")]


@pytest.mark.parametrize("mode", ["wait", "ontime", "late"])
def test_due_brief_is_dispatched_under_the_gate(mode):
    """불린 실행이 force=true 로 오면 휴장일에도, 이미 보낸 날에도 발송된다."""
    assert kick("US", modes={"US": mode}) == ["workflow run brief-us.yml --ref main -f force=false"]


def test_skip_is_not_dispatched():
    assert kick("KR", "US", modes={"KR": "skip", "US": "skip"}) == []


def test_running_brief_is_left_alone():
    """기다리는 실행이 이미 있으면 하나 더 부르지 않는다 — 대기열만 붐빈다."""
    assert kick("KR", modes={"KR": "wait"}, busy="1") == []


def test_unreadable_run_list_still_dispatches():
    """목록을 못 읽었다고 안 부르면 그날 브리핑을 놓친다. 하나 더 불려도 중복 검사가 막는다."""
    assert kick("KR", modes={"KR": "wait"}, list_fails=True) == \
        ["workflow run brief-kr.yml --ref main -f force=false"]


def test_each_market_is_judged_separately():
    assert kick("KR", "US", modes={"KR": "skip", "US": "wait"}) == \
        ["workflow run brief-us.yml --ref main -f force=false"]


def test_broken_gate_does_not_fail_the_caller():
    """게이트가 죽어도(빈 출력) 부른 워크플로는 계속 돈다 — 이건 덤이다."""
    assert kick("KR", modes={}) == []
