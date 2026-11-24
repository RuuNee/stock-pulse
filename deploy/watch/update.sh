#!/usr/bin/env bash
# 10분마다(stock-pulse-watch-update.timer): 새 코드가 있으면 받고 감시를 다시 띄운다.
# 저장소는 데이터 커밋이 잦다 — pipeline/·deploy/·requirements-watch.txt 가 안 바뀌었으면
# 받기만 하고 재시작하지 않는다(재시작하면 몇 초 동안 감시가 빈다).
set -euo pipefail
APP_DIR=/opt/stock-pulse
cd "$APP_DIR"

before=$(git rev-parse HEAD)
git fetch -q --depth 1 origin main
after=$(git rev-parse FETCH_HEAD)
[ "$before" = "$after" ] && exit 0

changed=$(git diff --name-only "$before" "$after" -- pipeline deploy requirements-watch.txt || echo pipeline)
git reset -q --hard "$after"
if [ -z "$changed" ]; then
  exit 0
fi

if echo "$changed" | grep -qx 'requirements-watch.txt'; then
  "$APP_DIR/.venv/bin/pip" install -q -r requirements-watch.txt
fi
if echo "$changed" | grep -q '^deploy/watch/'; then
  install -m 644 deploy/watch/stock-pulse-watch.service /etc/systemd/system/
  install -m 644 deploy/watch/stock-pulse-watch-update.service /etc/systemd/system/
  install -m 644 deploy/watch/stock-pulse-watch-update.timer /etc/systemd/system/
  install -m 755 deploy/watch/update.sh /usr/local/sbin/stock-pulse-watch-update
  systemctl daemon-reload
fi
systemctl restart stock-pulse-watch.service
echo "업데이트 ${before:0:7} → ${after:0:7}"
