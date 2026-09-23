#!/usr/bin/env bash
# One-time migration of the existing evotavern host from nginx to shared Caddy.
set -euo pipefail

SRC=$(cd "$(dirname "$0")/.." && pwd)
CADDY_DIR=/etc/caddy
SITES_DIR=$CADDY_DIR/sites
CADDYFILE=$CADDY_DIR/Caddyfile
MOONANSWER=$SITES_DIR/moonanswer.caddy
BEEPLAY=$SITES_DIR/beeplay.caddy
ENV_FILE=/etc/beeplay/beeplay.env
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP_DIR=$CADDY_DIR/backups/beeplay-caddy-$STAMP
COMMITTED=0
SWITCH_STARTED=0

fatal() { echo "FATAL: $*" >&2; exit 1; }

restore_config() {
  [ "$COMMITTED" = 0 ] || return 0
  [ -d "$BACKUP_DIR" ] || return 0

  echo "== restore shared Caddy configuration ==" >&2
  cp -a "$BACKUP_DIR/Caddyfile" "$CADDYFILE"
  if [ -f "$BACKUP_DIR/moonanswer.caddy" ]; then
    cp -a "$BACKUP_DIR/moonanswer.caddy" "$MOONANSWER"
  else
    rm -f "$MOONANSWER"
  fi
  if [ -f "$BACKUP_DIR/beeplay.caddy" ]; then
    cp -a "$BACKUP_DIR/beeplay.caddy" "$BEEPLAY"
  else
    rm -f "$BEEPLAY"
  fi
  cp -a "$BACKUP_DIR/beeplay.env" "$ENV_FILE"

  if [ "$SWITCH_STARTED" = 1 ]; then
    systemctl disable --now caddy || true
    systemctl enable --now nginx || true
    systemctl restart beeplay || true
  fi
}

trap restore_config EXIT

[ "$(id -u)" = 0 ] || fatal "run as root"
command -v caddy >/dev/null || fatal "caddy is not installed"
[ -f /etc/systemd/system/caddy.service ] || fatal "missing caddy.service"
[ -f /etc/caddy/cloudflare.env ] || fatal "missing Cloudflare environment used by Moonanswer"
[ -f "$CADDYFILE" ] || fatal "missing $CADDYFILE"
[ -f "$ENV_FILE" ] || fatal "missing $ENV_FILE; deploy BeePlay first"
systemctl is-active --quiet nginx || fatal "nginx must be active before the one-time migration"
if systemctl is-active --quiet caddy; then
  fatal "caddy is already active; inspect the host before running the migration"
fi

echo "== backup shared Caddy configuration =="
install -d -m 755 "$SITES_DIR" "$BACKUP_DIR"
cp -a "$CADDYFILE" "$BACKUP_DIR/Caddyfile"
cp -a "$ENV_FILE" "$BACKUP_DIR/beeplay.env"
[ ! -f "$MOONANSWER" ] || cp -a "$MOONANSWER" "$BACKUP_DIR/moonanswer.caddy"
[ ! -f "$BEEPLAY" ] || cp -a "$BEEPLAY" "$BACKUP_DIR/beeplay.caddy"

if ! grep -Fq 'import /etc/caddy/sites/*.caddy' "$CADDYFILE"; then
  echo "== split Moonanswer into its own site fragment =="
  awk '
    BEGIN { in_options = 0; depth = 0; options_done = 0 }
    !options_done && !in_options && $0 ~ /^[[:space:]]*\{/ { in_options = 1 }
    in_options {
      line = $0
      opens = gsub(/\{/, "{", line)
      closes = gsub(/\}/, "}", line)
      depth += opens - closes
      print
      if (depth == 0) { in_options = 0; options_done = 1 }
      next
    }
    options_done { print > moonanswer }
  ' moonanswer="$MOONANSWER.tmp" "$CADDYFILE" > "$CADDYFILE.tmp"
  grep -Fq 'moonanswer.com' "$MOONANSWER.tmp" || fatal "existing Caddyfile does not contain Moonanswer"
  printf '\nimport /etc/caddy/sites/*.caddy\n' >> "$CADDYFILE.tmp"
  install -m 644 "$MOONANSWER.tmp" "$MOONANSWER"
  install -m 644 "$CADDYFILE.tmp" "$CADDYFILE"
  rm "$MOONANSWER.tmp" "$CADDYFILE.tmp"
fi

echo "== install BeePlay site =="
install -m 644 "$SRC/deploy/beeplay.caddy" "$BEEPLAY"
set -a
. /etc/caddy/cloudflare.env
set +a
caddy validate --config "$CADDYFILE"

echo "== secure BeePlay environment =="
sed -i 's#^BEEPLAY_PUBLIC_URL=.*#BEEPLAY_PUBLIC_URL=https://beeplay.top#' "$ENV_FILE"
sed -i '/^BEEPLAY_ALLOW_INSECURE_CLAIMS=/d' "$ENV_FILE"

echo "== switch public edge =="
SWITCH_STARTED=1
systemctl disable --now nginx
if ! systemctl enable --now caddy; then
  fatal "Caddy failed to start"
fi
systemctl restart beeplay
COMMITTED=1
trap - EXIT

cat <<'EOF'
Migration complete. Existing HTTP claim cookies must be claimed again.

Manual fallback if Caddy needs diagnosis:
  systemctl disable --now caddy
  systemctl enable --now nginx
  sed -i 's#^BEEPLAY_PUBLIC_URL=.*#BEEPLAY_PUBLIC_URL=http://47.251.140.176#' /etc/beeplay/beeplay.env
  grep -q '^BEEPLAY_ALLOW_INSECURE_CLAIMS=' /etc/beeplay/beeplay.env || echo 'BEEPLAY_ALLOW_INSECURE_CLAIMS=1' >> /etc/beeplay/beeplay.env
  systemctl restart beeplay
EOF
