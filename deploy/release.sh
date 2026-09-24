#!/usr/bin/env bash
# Release Beeplay on the server, from an export of one commit:
#
#   sudo bash deploy/release.sh             # release
#   sudo bash deploy/release.sh --dry-run   # the checks only; nothing live changes
#
# beeplay-release runs this on a commit it downloaded from GitHub, when
# deploy/push.sh on a laptop asks it to; run it by hand only in an emergency.
#
# Before anything live is touched, the new code migrates a copy of the live
# database and its Caddy site is validated beside the others; either failing
# ends the release with the site untouched. The code that was live stays in
# /srv/beeplay.prev and comes back automatically if a later step fails, or if
# beeplay.top then fails its check through Caddy (deploy/beeplay-check).
set -euo pipefail

SRC=$(cd "$(dirname "$0")/.." && pwd)
APP=/srv/beeplay
PREV=/srv/beeplay.prev
NEXT=/srv/beeplay.next
STATE=/var/lib/beeplay
DB=$STATE/beeplay.db
BACKUPS=/var/backups/beeplay
# beeplay-release passes its stamp so a rollback can find this backup.
STAMP=${BEEPLAY_RELEASE_STAMP:-$(date +%Y%m%d-%H%M%S)}
BACKUP=$BACKUPS/beeplay-$STAMP.db

DRY_RUN=0
case "${1:-}" in
  "") ;;
  --dry-run) DRY_RUN=1 ;;
  *) echo "usage: release.sh [--dry-run]" >&2; exit 2 ;;
esac

[ "$(id -u)" = 0 ] || { echo "FATAL: run as root" >&2; exit 1; }
[ "$SRC" != "$APP" ] || { echo "FATAL: run from a checkout, not from $APP" >&2; exit 1; }
[ -f /etc/caddy/Caddyfile ] || { echo "FATAL: run deploy/setup-caddy.sh first" >&2; exit 1; }
[ -f /etc/caddy/cloudflare.env ] || { echo "FATAL: missing Caddy Cloudflare environment" >&2; exit 1; }

# Copies a tree for serving. Modes are set here, not inherited from the push:
# Caddy runs as its own user, and a checkout in a 0700 directory once made
# every asset answer 403.
sync_tree() {  # from to
  rsync -a --delete --chmod=Da+rx,Fa+r \
    --exclude '.git' --exclude '.venv' --exclude '.cache' --exclude '.local' --exclude '.env' \
    --exclude 'node_modules' --exclude 'beeplay.db*' --exclude 'games' --exclude 'failed' \
    --exclude 'logs' --exclude 'avatars' \
    "$1/" "$2/"
  chmod 755 "$2"
  chown -R beeplay:beeplay "$2"
}

db_version() {  # database file -> its alembic revision, or "none"
  sqlite3 -readonly "$1" "select version_num from alembic_version" 2>/dev/null || echo none
}

validate_caddy() {  # Caddyfile
  (set -a; . /etc/caddy/cloudflare.env; set +a; caddy validate --config "$1")
}

rollback_help() {
  cat <<HELP
To go back by hand:
  systemctl stop beeplay
  rm -rf $APP && cp -a $PREV $APP
  # only if the database version moved:
  sqlite3 $DB ".restore '$BACKUP'" && chown beeplay:beeplay $DB*
  cp $APP/deploy/beeplay.service /etc/systemd/system/ && systemctl daemon-reload
  install -m 644 $APP/deploy/beeplay.caddy /etc/caddy/sites/beeplay.caddy && systemctl reload caddy
  systemctl start beeplay && beeplay-check
Logs: journalctl -u beeplay -n 100
HELP
}

# The version to go back to: the code, the unit, the Caddy site, and the
# database too when this release moved its version, since the previous code
# refuses a database it does not know. That loses what players wrote since
# the backup, so it needs someone at the terminal to type "restore".
restore_previous() {
  set +e
  echo "== putting back the previous release ==" >&2
  if [ ! -d "$PREV" ]; then
    echo "FATAL: there is no $PREV to go back to; the new release stays." >&2
    rollback_help >&2
    return
  fi
  local moved restore_db=0 answer="" minutes
  moved=$(db_version "$DB")
  if [ "$moved" != "$BEFORE" ]; then
    minutes=$(( ($(date +%s) - $(stat -c %Y "$BACKUP")) / 60 + 1 ))
    echo "This release moved the database from $BEFORE to $moved. Going back restores the" >&2
    echo "backup from $(date -r "$BACKUP" +%H:%M): about $minutes min of likes, uploads and sign-ups are lost." >&2
    if { : </dev/tty; } 2>/dev/null; then
      read -r -p 'Type "restore" to put back the previous code and that database: ' answer </dev/tty || answer=""
    fi
    if [ "$answer" = restore ]; then
      restore_db=1
    else
      echo "Not restored: the new release stays in place." >&2
      rollback_help >&2
      return
    fi
  fi
  systemctl stop beeplay
  rm -rf "$APP.failed"
  mv "$APP" "$APP.failed"
  cp -a "$PREV" "$APP"
  if [ "$restore_db" = 1 ]; then
    sqlite3 "$DB" ".restore '$BACKUP'" && chown beeplay:beeplay "$DB"*
  fi
  cp "$APP/deploy/beeplay.service" /etc/systemd/system/beeplay.service
  install -m 755 "$APP/deploy/beeplay-ops" /usr/local/bin/beeplay-ops
  install -m 644 "$APP/deploy/beeplay.caddy" /etc/caddy/sites/beeplay.caddy
  systemctl daemon-reload
  systemctl start beeplay
  validate_caddy /etc/caddy/Caddyfile >/dev/null 2>&1 && systemctl reload caddy
  sleep 3
  if beeplay-check; then
    echo "The previous release is back and passes its check. The failed one is in $APP.failed." >&2
  else
    echo "The previous release is back but still fails its check: look now." >&2
    rollback_help >&2
  fi
}

SWAPPED=0
DONE=0
BEFORE=none
on_exit() {
  local status=$?
  if [ "$SWAPPED" = 1 ] && [ "$DONE" = 0 ]; then
    restore_previous
  fi
  rm -rf "$NEXT"  # holds a copy of the database
  exit "$status"
}
trap on_exit EXIT

echo "== environment =="
if [ "$DRY_RUN" = 0 ]; then
  install -d -m 755 /etc/beeplay
  if [ ! -f /etc/beeplay/beeplay.env ]; then
    install -m 640 -g beeplay "$SRC/deploy/beeplay.env" /etc/beeplay/beeplay.env
    echo "installed /etc/beeplay/beeplay.env"
  fi
  install -d -o beeplay -g beeplay "$STATE" "$STATE/games" "$STATE/failed" "$STATE/logs" "$STATE/avatars"
fi

echo "== rehearse =="
# A scratch copy of the new code, with its own dependencies, migrates a copy
# of the live database. The release goes ahead only if that works.
rm -rf "$NEXT"
sync_tree "$SRC" "$NEXT"
sudo -u beeplay uv sync --project "$NEXT" --frozen --no-dev --quiet
if [ -f "$DB" ]; then
  # .backup, not cp: the live database is in WAL mode.
  if [ "$DRY_RUN" = 1 ]; then
    sqlite3 "$DB" ".backup '$NEXT/rehearsal.db'"
  else
    install -d -m 700 "$BACKUPS"
    sqlite3 "$DB" ".backup '$BACKUP'"
    echo "database saved to $BACKUP"
    cp "$BACKUP" "$NEXT/rehearsal.db"
  fi
  chown beeplay:beeplay "$NEXT/rehearsal.db"
fi
BEFORE=$(db_version "$NEXT/rehearsal.db")
if ! (set -a; . /etc/beeplay/beeplay.env; set +a
      export BEEPLAY_DB_PATH=$NEXT/rehearsal.db BEEPLAY_EVENTS_LOG=$NEXT/rehearsal-events.jsonl
      cd "$NEXT" && sudo --preserve-env -u beeplay "$NEXT/.venv/bin/python" -m app.ops migrate
     ) >"$NEXT/rehearsal.log" 2>&1; then
  tail -n 20 "$NEXT/rehearsal.log" >&2
  echo "FATAL: this code cannot migrate a copy of the live database (at $BEFORE). Nothing live was changed." >&2
  exit 1
fi
AFTER=$(db_version "$NEXT/rehearsal.db")
if [ "$AFTER" = "$BEFORE" ]; then
  echo "migrate: ok on a copy (database stays at $BEFORE)"
else
  echo "migrate: ok on a copy (database $BEFORE -> $AFTER)"
fi
# The new BeePlay site, validated beside the other sites as it will run.
mkdir -p "$NEXT/caddy/sites"
for site in /etc/caddy/sites/*.caddy; do
  [ "$(basename "$site")" = beeplay.caddy ] || cp "$site" "$NEXT/caddy/sites/"
done
cp "$NEXT/deploy/beeplay.caddy" "$NEXT/caddy/sites/beeplay.caddy"
sed "s#/etc/caddy/sites/#$NEXT/caddy/sites/#g" /etc/caddy/Caddyfile >"$NEXT/caddy/Caddyfile"
if ! validate_caddy "$NEXT/caddy/Caddyfile" >"$NEXT/caddy.log" 2>&1; then
  tail -n 20 "$NEXT/caddy.log" >&2
  echo "FATAL: the new Caddy site is invalid. Nothing live was changed." >&2
  exit 1
fi
echo "caddy: the new site config is valid"
bash -n "$NEXT/deploy/beeplay-check"
for tool in beeplay-notify beeplay-release; do
  python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read())' "$NEXT/deploy/$tool"
done

if [ "$DRY_RUN" = 1 ]; then
  echo "== live site, as the new check sees it =="
  bash "$NEXT/deploy/beeplay-check" || true
  echo "dry run passed: nothing live was changed."
  exit 0
fi

echo "== code =="
# /srv/beeplay.prev is what a failure goes back to, so it only ever takes a
# release that works: the live one, if the site serves it right now.
if bash "$NEXT/deploy/beeplay-check" --files-only >/dev/null 2>&1; then
  rm -rf "$PREV"
  cp -a "$APP" "$PREV"
else
  echo "the live site fails its check: keeping $PREV as the version to go back to"
fi
SWAPPED=1
sync_tree "$SRC" "$APP"
sudo -u beeplay uv sync --project "$APP" --frozen --no-dev

echo "== system config =="
cp "$APP/deploy/beeplay.service" "$APP/deploy/beeplay-check.service" "$APP/deploy/beeplay-check.timer" /etc/systemd/system/
install -m 755 "$APP/deploy/beeplay-ops" /usr/local/bin/beeplay-ops
install -m 755 "$APP/deploy/beeplay-check" /usr/local/bin/beeplay-check
install -m 755 "$APP/deploy/beeplay-notify" /usr/local/bin/beeplay-notify
# install replaces the file rather than rewriting it, so the beeplay-release
# that is running this release is not disturbed.
install -m 755 "$APP/deploy/beeplay-release" /usr/local/bin/beeplay-release
install -d -m 755 /etc/caddy/sites
cp -a /etc/caddy/sites/beeplay.caddy "/etc/caddy/sites/beeplay.caddy.$STAMP.prev" 2>/dev/null || true
install -m 644 "$APP/deploy/beeplay.caddy" /etc/caddy/sites/beeplay.caddy
if ! validate_caddy /etc/caddy/Caddyfile; then
  if [ -f "/etc/caddy/sites/beeplay.caddy.$STAMP.prev" ]; then
    mv "/etc/caddy/sites/beeplay.caddy.$STAMP.prev" /etc/caddy/sites/beeplay.caddy
  else
    rm -f /etc/caddy/sites/beeplay.caddy
  fi
  echo "FATAL: Caddy configuration is invalid; previous BeePlay fragment restored" >&2
  exit 1
fi
rm -f "/etc/caddy/sites/beeplay.caddy.$STAMP.prev"
systemctl daemon-reload

echo "== migrate =="
# Stopped so nothing writes mid copy-and-swap. The same migration already
# worked on a copy, so this is not where a release is expected to fail.
systemctl stop beeplay
beeplay-ops migrate
beeplay-ops refresh-reporter
systemctl start beeplay
systemctl reload caddy

echo "== verify =="
up=0
for i in $(seq 1 20); do
  if [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ || true)" = 200 ]; then
    echo "app up after ${i}s"
    up=1
    break
  fi
  sleep 1
done
[ "$up" = 1 ] || { echo "FATAL: the app did not answer on 127.0.0.1:8000 within 20s" >&2; exit 1; }
# Players go through Caddy, which serves /assets/ itself: check the same way.
checked=0
for _ in 1 2 3; do
  if beeplay-check; then
    checked=1
    break
  fi
  sleep 2
done
[ "$checked" = 1 ] || { echo "FATAL: beeplay.top fails its check through Caddy" >&2; exit 1; }
DONE=1
systemctl enable --now beeplay-check.timer || echo "WARNING: the 5-minute check (beeplay-check.timer) did not start" >&2
echo "released $STAMP"
beeplay-ops list
