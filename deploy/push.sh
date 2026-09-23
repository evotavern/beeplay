#!/usr/bin/env bash
# From a laptop checkout: copy this tree to the server and release it.
#   deploy/push.sh            # host defaults to the "evotavern" ssh alias
set -euo pipefail
HOST=${BEEPLAY_HOST:-evotavern}
cd "$(dirname "$0")/.."
# .env holds local provider keys (deploy/local.sh); the server reads
# /etc/beeplay/beeplay.env instead, so it must never be copied there.
rsync -a --delete --exclude '.git' --exclude '.venv' --exclude '.claude' --exclude '.env' \
  --exclude 'beeplay.db*' --exclude 'games' --exclude 'failed' --exclude 'logs' \
  ./ "$HOST:/root/beeplay-release/"
ssh "$HOST" bash /root/beeplay-release/deploy/release.sh
