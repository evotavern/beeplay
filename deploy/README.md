# Deploying Beeplay

Uncontainerized: uvicorn under systemd on localhost, Caddy in front for TLS
and static files. Target host serves `beeplay.top`.

## Prerequisites

DNS `A` records pointing at the server before starting Caddy — it obtains
certificates over HTTP-01 and will fail noisily without them:

| name | type |
| --- | --- |
| `beeplay.top` | A |
| `www.beeplay.top` | A |

Ports 80 and 443 must be reachable. Port 80 is required even though the site
is HTTPS-only: it carries the ACME challenge and the HTTP→HTTPS redirect.

## Install

```bash
# 1. service account and code
sudo useradd --system --home /srv/beeplay --shell /usr/sbin/nologin beeplay
sudo mkdir -p /srv/beeplay
sudo rsync -a --exclude '.git' --exclude '.venv' --exclude 'beeplay.db*' ./ /srv/beeplay/
sudo chown -R beeplay:beeplay /srv/beeplay

# 2. dependencies (uv installs a .venv the unit points at)
sudo -u beeplay uv sync --project /srv/beeplay --frozen

# 3. Caddy runs as its own user and must be able to READ the assets.
#    Source files are often mode 0600; a+rX grants read on files and
#    traversal on directories without making anything executable.
sudo chmod -R a+rX /srv/beeplay/assets

# 4. application service
sudo cp deploy/beeplay.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now beeplay.service

# 5. reverse proxy
sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl reload caddy
```

Caddy ships its own `caddy.service` with the official package — don't write
one. `systemctl reload caddy` applies Caddyfile changes without dropping
connections.

## Verify

```bash
systemctl status beeplay.service
curl -sI https://beeplay.top | head -1
curl -s https://beeplay.top/assets/js/app.js -o /dev/null -w '%{http_code}\n'
journalctl -u beeplay.service -n 50 --no-pager
```

## State

The SQLite database lives at `/var/lib/beeplay/beeplay.db`, created by the
unit's `StateDirectory=`. It is deliberately outside `/srv/beeplay`, which
`ProtectSystem=strict` makes read-only. Locally the app falls back to
`beeplay.db` beside the code; `BEEPLAY_DB_PATH` overrides both.

Back it up with SQLite's own command, not `cp` — copying a database with a
live WAL can capture a torn state:

```bash
sudo -u beeplay sqlite3 /var/lib/beeplay/beeplay.db ".backup '/var/backups/beeplay-$(date +%F).db'"
```

## Deploying a change

```bash
sudo rsync -a --exclude '.git' --exclude '.venv' --exclude 'beeplay.db*' ./ /srv/beeplay/
sudo chown -R beeplay:beeplay /srv/beeplay
sudo chmod -R a+rX /srv/beeplay/assets
sudo -u beeplay uv sync --project /srv/beeplay --frozen
sudo systemctl restart beeplay.service
```

There are no schema migrations yet. Add Alembic before the first model change
that has to preserve existing rows.

## Not yet wired

The `games.beeplay.top` block in the Caddyfile is commented out. It serves
model-generated games from a separate origin — which is a security boundary,
not a convenience, since same-origin would expose the session cookie to
generated code. Uncomment it once generation lands and the DNS record exists.
