#!/usr/bin/env bash
# 깨어난 김에 장전 브리핑도 깨운다 — 예약 실행 하나하나를 브리핑의 기회로 쓴다.
#
# 2026-11-03 GitHub 은 예약 실행을 5~10시간 밀고 대부분 버렸다. 미장 브리핑 슬롯은
# 하루 12개 중 2개만 깼고, 09:25Z~14:40Z 에는 어떤 워크플로도 깨지 않았다. 마지막으로
# 깬 미장 슬롯(08:32Z = 03:32 ET)은 창 시작 283분 전이라 기다리지 않고 끝났고, 그날
# 미장 브리핑은 개장 전에 나가지 못했다. 그런데 brief-kr 은 09:24Z 에 깨어 있었다 —
# 그 실행이 미장 브리핑을 불러 줬으면 정시에 나갔다. 같은 날 국장 브리핑(09:54 KST
# 지각)도 전날 밤 data-sync·pulse·brief-kr-close 가 창 시작 3~5시간 전에 열 번 깨어 있었다.
#
# 그래서 예약 워크플로는 전부 체크아웃 직후 이걸 부른다. 시장마다 게이트를 묻고
# (표준 라이브러리만 — pip install 전), 브리핑이 기다리거나 보낼 차례(wait|ontime|late)인데
# 그 시장 브리핑 실행이 하나도 안 돌고 있으면 workflow_dispatch(force=false)로 부른다.
# dispatch 는 예약 큐를 거치지 않아 몇 초 만에 시작하고, 불린 실행이 게이트를 처음부터
# 다시 타서 창 시작까지 기다렸다가 보낸다. GITHUB_TOKEN 이 만든 이벤트는 새 실행을
# 만들지 않는데 workflow_dispatch 는 예외다 — 그래서 부르는 쪽에 `actions: write` 가 필요하다.
#
# 덤이므로 무슨 일이 있어도 부른 워크플로를 막지 않는다 (항상 exit 0).
#
#   bash .github/scripts/kick-briefs.sh KR US
set -uo pipefail

for market in "$@"; do
  mode=$(python3 -m pipeline.run gate --market "$market" | sed -n 2p)
  case "$mode" in
    wait|ontime|late) ;;
    *) continue ;;   # skip — 휴장일·이미 보냄·창이 아직 멂·지각 마감 지남 (이유는 위 stderr)
  esac

  workflow="brief-$(printf '%s' "$market" | tr '[:upper:]' '[:lower:]').yml"
  # 이미 돌거나 줄 선 실행이 있으면 그 실행이 게이트를 탄다. 목록을 못 읽으면 그냥
  # 부른다 — 하나 더 불려도 동시성 그룹에서 기다리다 중복 검사로 끝난다.
  busy=$(gh run list --workflow "$workflow" --limit 20 --json status \
           --jq '[.[] | select(.status != "completed")] | length' || echo 0)
  if [ "${busy:-0}" != "0" ]; then
    echo "$market: $workflow 실행이 이미 돌고 있습니다 — 그대로 둡니다"
    continue
  fi

  if gh workflow run "$workflow" --ref main -f force=false; then
    echo "$market: 브리핑 차례($mode) — $workflow 를 불렀습니다"
  else
    echo "$market: $workflow 호출 실패 — 남은 슬롯에 맡깁니다"
  fi
done
exit 0
