#!/usr/bin/env bash
# Ship a green pull request to beeplay.top: see deploy/push.py, or run it
# without arguments.
#   deploy/push.sh 12             briefing, then type "ship": merges PR #12 and releases it
#   deploy/push.sh --dry-run 12   the briefing and the server's checks; nothing changes
#   deploy/push.sh main           releases main as it is
#   deploy/push.sh rollback       puts the previous release back
#   deploy/push.sh setup          once per server
exec python3 "$(dirname "$0")/push.py" "$@"
