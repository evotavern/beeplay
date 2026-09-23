#!/usr/bin/env bash
# Release Beeplay on the server, from a checkout of this repository:
#
#   sudo bash deploy/release.sh
#
# deploy/push.sh does the copy and runs this for you from a laptop.
# Backs up the database first, keeps the previous code for rollback, and
# only reports success once the app answers.
set -euo pipefail

SRC=$(cd "$(dirname "$0")/.." && pwd)
APP=/srv/beeplay
PREV=/srv/beeplay.prev
STATE=/var/lib/beeplay
DB=$STATE/beeplay.db
BACKUPS=/var/backups/beeplay
STAMP=$(date +%Y%m%d-%H%M%S)

[ "$(id -u)" = 0 ] || { echo "FATAL: run as root" >&2; exit 1; }
[ "$SRC" != "$APP" ] || { echo "FATAL: run from a checkout, not from $APP" >&2; exit 1; }

echo "== environment =="
install -d -m 755 /etc/beeplay
if [ ! -f /etc/beeplay/beeplay.env ]; then
  install -m 640 -g beeplay "$SRC/deploy/beeplay.env" /etc/beeplay/beeplay.env
  echo "installed /etc/beeplay/beeplay.env"
fi
install -d -o beeplay -g beeplay "$STATE" "$STATE/games" "$STATE/failed" "$STATE/logs" "$STATE/avatars"

echo "== backup =="
install -d -m 700 "$BACKUPS"
if [ -f "$DB" ]; then
  # .backup, not cp: the live database is in WAL mode.
  sqlite3 "$DB" ".backup '$BACKUPS/beeplay-$STAMP.db'"
  echo "database saved to $BACKUPS/beeplay-$STAMP.db"
fi

echo "== code =="
rm -rf "$PREV"
cp -a "$APP" "$PREV"
rsync -a --delete \
  --exclude '.git' --exclude '.venv' --exclude '.cache' --exclude '.local' --exclude '.env' \
  --exclude 'beeplay.db*' --exclude 'games' --exclude 'failed' --exclude 'logs' --exclude 'avatars' \
  "$SRC/" "$APP/"
chown -R beeplay:beeplay "$APP"
chmod -R a+rX "$APP/assets"
sudo -u beeplay uv sync --project "$APP" --frozen --no-dev

echo "== system config =="
cp "$APP/deploy/beeplay.service" /etc/systemd/system/beeplay.service
install -m 755 "$APP/deploy/beeplay-ops" /usr/local/bin/beeplay-ops
[ -f /etc/caddy/Caddyfile ] || { echo "FATAL: run deploy/setup-caddy.sh first" >&2; exit 1; }
[ -f /etc/caddy/cloudflare.env ] || { echo "FATAL: missing Caddy Cloudflare environment" >&2; exit 1; }
install -d -m 755 /etc/caddy/sites
cp -a /etc/caddy/sites/beeplay.caddy "/etc/caddy/sites/beeplay.caddy.$STAMP.prev" 2>/dev/null || true
install -m 644 "$APP/deploy/beeplay.caddy" /etc/caddy/sites/beeplay.caddy
set -a
. /etc/caddy/cloudflare.env
set +a
if ! caddy validate --config /etc/caddy/Caddyfile; then
  if [ -f "/etc/caddy/sites/beeplay.caddy.$STAMP.prev" ]; then
    mv "/etc/caddy/sites/beeplay.caddy.$STAMP.prev" /etc/caddy/sites/beeplay.caddy
  else
    rm -f /etc/caddy/sites/beeplay.caddy
  fi
  caddy validate --config /etc/caddy/Caddyfile >/dev/null 2>&1 || true
  echo "FATAL: Caddy configuration is invalid; previous BeePlay fragment restored" >&2
  exit 1
fi
rm -f "/etc/caddy/sites/beeplay.caddy.$STAMP.prev"
systemctl daemon-reload

echo "== migrate =="
# Stopped for the migration so nothing writes mid copy-and-swap; startup would
# migrate too, but here a failure stops the release before anything is served.
systemctl stop beeplay
beeplay-ops migrate
beeplay-ops refresh-reporter
systemctl start beeplay
systemctl reload caddy

echo "== verify =="
for i in $(seq 1 20); do
  code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ || true)
  if [ "$code" = 200 ]; then
    echo "up after ${i}s"
    beeplay-ops list
    exit 0
  fi
  sleep 1
done

cat >&2 <<ROLLBACK
FATAL: app did not answer 200 within 20s. To roll back:
  systemctl stop beeplay
  rm -rf $APP && mv $PREV $APP
  sudo -u beeplay sqlite3 $DB ".restore '$BACKUPS/beeplay-$STAMP.db'"
  cp $APP/deploy/beeplay.service /etc/systemd/system/ && systemctl daemon-reload
  systemctl start beeplay
Logs: journalctl -u beeplay -n 100
ROLLBACK
exit 1
