"""워크플로 YAML 자체가 성립하는지.

2026-07-28 개정 중 커밋 스텝을 `run: bash ... "chore(brief): KR ..."` 한 줄로 줄였다가
따옴표 밖의 `: ` 때문에 네 워크플로가 전부 파싱 불가가 됐다. GitHub 은 이런 파일을
조용히 무시하므로(워크플로가 목록에서 사라진다) 로컬에서 먼저 잡는다.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

GITHUB = Path(__file__).resolve().parent.parent / ".github"
WORKFLOW_DIR = GITHUB / "workflows"
SCRIPT_DIR = GITHUB / "scripts"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml"))
BRIEFS = ["brief-kr.yml", "brief-us.yml"]


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def triggers(data: dict) -> dict:
    # PyYAML 은 따옴표 없는 `on:` 을 불리언 True 로 읽는다 (YAML 1.1).
    return data.get(True) or data.get("on") or {}


def run_lines(data: dict) -> list[str]:
    """실제로 실행되는 명령만. 주석은 여기 안 들어온다."""
    return [step["run"] for spec in data["jobs"].values()
            for step in spec["steps"] if step.get("run")]


def test_expected_workflows_present():
    names = {p.name for p in WORKFLOWS}
    assert {"brief-kr.yml", "brief-us.yml", "data-sync.yml", "pulse.yml"} <= names


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_parses_and_has_jobs(path):
    data = load(path)
    assert data.get("jobs"), f"{path.name}: jobs 가 없습니다"
    assert triggers(data), f"{path.name}: 트리거가 없습니다"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_referenced_scripts_exist(path):
    for command in run_lines(load(path)):
        for token in command.split():
            if token.startswith(".github/scripts/"):
                assert (SCRIPT_DIR / Path(token).name).exists(), \
                    f"{path.name}: {token} 가 없습니다"


@pytest.mark.parametrize("name", BRIEFS)
def test_brief_does_not_rebuild(name):
    """브리핑 발송 경로에 전체 재빌드가 다시 들어오면 Actions 무료 한도를 넘긴다(스펙 §12)."""
    commands = run_lines(load(WORKFLOW_DIR / name))
    assert not [c for c in commands if "--rebuild" in c]


@pytest.mark.parametrize("name", BRIEFS)
def test_brief_has_own_concurrency_group(name):
    """data-sync(26분) 뒤에 큐잉되면 발송 창을 통째로 놓친다."""
    group = load(WORKFLOW_DIR / name)["concurrency"]["group"]
    assert group != "stock-pulse-data", f"{name}: 데이터 잡과 그룹을 공유하면 안 됩니다"


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_scheduled_jobs_checkout_main(path):
    """스케줄 트리거는 예약 시점 SHA 를 준다 — 최대 3시간 묵은 트리로 판정하게 된다."""
    data = load(path)
    if not triggers(data).get("schedule"):
        return
    for job, spec in data["jobs"].items():
        checkouts = [s for s in spec["steps"]
                     if str(s.get("uses", "")).startswith("actions/checkout")]
        assert checkouts, f"{path.name}/{job}: checkout 이 없습니다"
        for step in checkouts:
            assert (step.get("with") or {}).get("ref") == "main", \
                f"{path.name}/{job}: checkout 에 ref: main 이 필요합니다"
