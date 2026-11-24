#!/usr/bin/env bash
# 속보 감시 서버 설치 — 우분투 22.04/24.04 (오라클 클라우드 무료 등급 기준). 여러 번 돌려도 된다.
#
#   sudo bash setup.sh        (보통은 GitHub Actions 'watch-deploy' 가 SSH 로 돌린다)
#
# 하는 일: 패키지 → 전용 계정 → 코드(pipeline·deploy 만) → 가상환경 → systemd
#          (감시 상시 실행 + 10분마다 새 코드 확인). 키 파일은 비어 있으면 틀만 만든다.
set -euo pipefail

REPO="${REPO:-https://github.com/RuuNee/stock-pulse.git}"
APP_DIR=/opt/stock-pulse
APP_USER=stockpulse
STATE_DIR=/var/lib/stock-pulse
ENV_FILE=/etc/stock-pulse-watch.env

if [ "$(id -u)" -ne 0 ]; then
  echo "sudo 로 실행하세요" >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -y -q
apt-get install -y -q --no-install-recommends git python3 python3-venv ca-certificates tzdata

id -u "$APP_USER" >/dev/null 2>&1 || \
  useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin "$APP_USER"
install -d -o "$APP_USER" -g "$APP_USER" -m 750 "$STATE_DIR" "$STATE_DIR/watch" "$STATE_DIR/cache"

# 저장소가 커서(data/ 커밋이 하루 수십 MB) 코드 폴더만 받는다. 루트 파일은 늘 따라온다.
if [ ! -d "$APP_DIR/.git" ]; then
  git clone -q --depth 1 --filter=blob:none --sparse "$REPO" "$APP_DIR"
fi
git -C "$APP_DIR" sparse-checkout set pipeline deploy
git -C "$APP_DIR" fetch -q --depth 1 origin main
git -C "$APP_DIR" reset -q --hard FETCH_HEAD

python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install -q --upgrade pip
"$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements-watch.txt"

if [ ! -f "$ENV_FILE" ]; then
  install -m 640 -o root -g "$APP_USER" /dev/null "$ENV_FILE"
  cat > "$ENV_FILE" <<'EOT'
# 속보 감시 서버 키 — GitHub Actions 'watch-deploy' 가 저장소 시크릿으로 채운다.
ANTHROPIC_API_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
EOT
fi

install -m 644 "$APP_DIR/deploy/watch/stock-pulse-watch.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/watch/stock-pulse-watch-update.service" /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/watch/stock-pulse-watch-update.timer" /etc/systemd/system/
install -m 755 "$APP_DIR/deploy/watch/update.sh" /usr/local/sbin/stock-pulse-watch-update

# 로그가 무료 서버의 작은 디스크를 채우지 않게
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=200M\n' > /etc/systemd/journald.conf.d/stock-pulse.conf
systemctl restart systemd-journald

systemctl daemon-reload
systemctl enable --now stock-pulse-watch-update.timer
systemctl enable stock-pulse-watch.service
systemctl restart stock-pulse-watch.service
sleep 3
systemctl --no-pager --lines=15 status stock-pulse-watch.service || true
