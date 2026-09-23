#!/usr/bin/env bash
# Runs this worktree only; reads keys from its ignored .env file.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ ! -f .env ]]; then
    (umask 077; cp .env.example .env)
fi
exec uv run uvicorn app.main:app --env-file .env --host 127.0.0.1 --port "${BEEPLAY_LOCAL_PORT:-8021}"
