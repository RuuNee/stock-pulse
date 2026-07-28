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
def test_rehearsal_never_commits(name):
    """리허설(`send=false` dispatch)이 브리핑 파일을 커밋하면 중복 게이트가 그날
    진짜 발송을 막는다 — 고치려던 사고를 손으로 재현하는 꼴이 된다."""
    steps = load(WORKFLOW_DIR / name)["jobs"]["brief"]["steps"]
    commit = [s for s in steps if "commit-data.sh" in (s.get("run") or "")]
    assert commit, f"{name}: 커밋 스텝을 못 찾았습니다"
    for step in commit:
        assert "steps.gate.outputs.send != ''" in step.get("if", ""), \
            f"{name}: 커밋 스텝이 발송 여부로 가드되지 않습니다"


@pytest.mark.parametrize("name", BRIEFS)
def test_scheduled_run_always_sends(name):
    """스케줄 실행에서 `--send` 가 빠지면 브리핑이 조용히 안 나간다."""
    gate = [s for s in load(WORKFLOW_DIR / name)["jobs"]["brief"]["steps"]
            if s.get("id") == "gate"][0]
    body = gate["run"]
    assert 'send="--send"' in body, f"{name}: 기본값이 발송이어야 합니다"
    # 리허설로 떨어지는 분기는 workflow_dispatch 안에만 있어야 한다.
    assert 'if [ "$EVENT" != "schedule" ]; then' in body


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
