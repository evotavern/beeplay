#!/usr/bin/env bash
# Repeatable local checks for deployment configuration.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"

uv run python -m unittest discover -s tests -v
# One file per call: `bash -n a b` checks only a.
for script in deploy/release.sh deploy/setup-caddy.sh deploy/push.sh deploy/test-config.sh \
    deploy/beeplay-check deploy/beeplay-ops deploy/local.sh; do
  bash -n "$script"
done
python3 -c 'import ast, sys; ast.parse(open(sys.argv[1]).read())' deploy/beeplay-notify

if command -v caddy >/dev/null; then
  work=$(mktemp -d)
  trap 'rm -rf "$work"' EXIT
  cat > "$work/Caddyfile" <<EOF
{
	local_certs
	http_port 18080
	https_port 18443
}

import $ROOT/deploy/beeplay.caddy
EOF
  caddy validate --config "$work/Caddyfile"
else
  echo "caddy not installed; skipped Caddyfile validation" >&2
fi
