#!/usr/bin/env bash
# From a laptop checkout: copy this tree to the server and release it.
#   deploy/push.sh             # release; host defaults to the "evotavern" ssh alias
#   deploy/push.sh --dry-run   # the release's checks only; nothing live changes
set -euo pipefail
HOST=${BEEPLAY_HOST:-evotavern}
MODE=
case "${1:-}" in
  "") ;;
  --dry-run) MODE=--dry-run ;;
  *) echo "usage: deploy/push.sh [--dry-run]" >&2; exit 2 ;;
esac
cd "$(dirname "$0")/.."
# .env holds local provider keys (deploy/local.sh); the server reads
# /etc/beeplay/beeplay.env instead, so it must never be copied there. File
# modes here don't matter: release.sh sets them on the server.
rsync -a --delete --exclude '.git' --exclude '.venv' --exclude '.claude' --exclude '.env' \
  --exclude 'node_modules' --exclude 'beeplay.db*' --exclude 'games' --exclude 'failed' \
  --exclude 'logs' --exclude 'avatars' \
  ./ "$HOST:/root/beeplay-release/"
# A terminal on the server lets release.sh ask before restoring the database.
TTY=
[ -t 0 ] && TTY=-t
ssh $TTY "$HOST" bash /root/beeplay-release/deploy/release.sh $MODE
