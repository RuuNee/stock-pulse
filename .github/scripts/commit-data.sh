#!/usr/bin/env bash
# 재생성된 data/ 를 main 에 올린다. 모든 데이터 워크플로가 이걸 쓴다.
#
# 이 저장소의 잡들은 서로 겹친다. GitHub 스케줄러 지연이 6~202분으로 널뛰어서
# 예약 순서와 실제 실행 순서가 다르고, 전부 같은 JSON 을 다시 만든다. 그래서
# push 는 항상 rejected 를 각오해야 한다 — 2026-07-27 에 단발 push 가 거절되며
# 25분치 재계산 결과가 통째로 날아갔다.
#
#   - 거절되면 origin/main 위로 rebase 해서 다시 올린다.
#   - 충돌 시 `-X theirs` = rebase 가 재생 중인 커밋(=방금 만든 데이터)을 채택한다.
#     전부 재생성 가능한 산출물이고 우리 쪽이 더 최신이므로 이게 맞다.
#   - rebase 자체가 깨지면 abort 하고 다시 fetch 해서 재시도한다.
set -euo pipefail

message="${1:?commit message required}"
attempts="${2:-5}"

git config user.name "stock-pulse-bot"
git config user.email "actions@github.com"

git add data/
if git diff --cached --quiet; then
  echo "데이터 변경 없음 — 커밋 생략"
  exit 0
fi
git commit -m "$message"

for attempt in $(seq 1 "$attempts"); do
  if git push origin HEAD:main; then
    echo "push 성공 (시도 $attempt/$attempts)"
    exit 0
  fi
  echo "push 거절 — origin/main 위로 다시 얹습니다 (시도 $attempt/$attempts)"
  git fetch origin main
  if ! git rebase -X theirs FETCH_HEAD; then
    git rebase --abort || true
    sleep 5
  fi
done

echo "push $attempts회 실패 — 데이터가 올라가지 않았습니다" >&2
exit 1
