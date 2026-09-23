# Deploying Beeplay

Nginx on port 80 serves `/assets/` and `/games/` from disk and proxies
everything else to uvicorn on `127.0.0.1:8000`. The current server is
`http://47.251.140.176/` (ssh alias `evotavern`).

## Plain HTTP for now

The site runs without TLS. Claim cookies are bearer credentials, so the app
only issues them over HTTP because `/etc/beeplay/beeplay.env` sets
`BEEPLAY_ALLOW_INSECURE_CLAIMS=1`. Moving to HTTPS later:

1. Put TLS in front (Caddy, or certbot with Nginx). Nginx already forwards
   `X-Forwarded-Proto`, and uvicorn runs with `--proxy-headers`.
2. In `/etc/beeplay/beeplay.env`, delete `BEEPLAY_ALLOW_INSECURE_CLAIMS=1`
   and set `BEEPLAY_PUBLIC_URL=https://…`.
3. `systemctl restart beeplay`. Cookies pick up the `Secure` flag on their
   own; testers claim again once.

## Releasing

From a laptop checkout:

```bash
deploy/push.sh
```

This copies the tree to `/root/beeplay-release/` and runs
`deploy/release.sh` there, which:

- installs `/etc/beeplay/beeplay.env` if missing (never overwrites it)
- backs the database up to `/var/backups/beeplay/beeplay-<time>.db`
- keeps the previous code at `/srv/beeplay.prev`
- syncs code, installs dependencies, the systemd unit, the Nginx site and
  `/usr/local/bin/beeplay-ops`
- stops the app, migrates the schema (`beeplay-ops migrate`), adds the crash
  reporter to games installed before it existed (`beeplay-ops
  refresh-reporter`), starts the app
- waits for HTTP 200 and prints rollback commands if it never comes

Schema changes are Alembic migrations in `migrations/versions/`. The app also
migrates on startup, so a plain restart is always safe.

## First install on a new server

```bash
sudo apt-get update && sudo apt-get install -y curl nginx sqlite3 rsync
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
sudo useradd --system --home /srv/beeplay --shell /usr/sbin/nologin beeplay
sudo mkdir -p /srv/beeplay && sudo chown beeplay:beeplay /srv/beeplay
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sfn /etc/nginx/sites-available/beeplay /etc/nginx/sites-enabled/beeplay
```

Then `deploy/push.sh`, and `systemctl enable beeplay nginx`. Open TCP port 80
in the cloud firewall.

## State

Everything lives in `/var/lib/beeplay`:

| Path | What |
|------|------|
| `beeplay.db` | SQLite: users, works (with `status`), `work_events`, `health_events`, `failed_uploads` |
| `games/<artifact>/` | one directory per uploaded version; replaced versions stay |
| `failed/<id>.zip` | uploads that failed validation, waiting for an operator |
| `logs/events.jsonl` | one JSON line per event; the journal has the same lines |

## Operating the event

```bash
beeplay-ops list                  # every game: id, status, owner, artifact, title
beeplay-ops failed                # broken uploads waiting for a fix
beeplay-ops import ~/fixed --from-failed 7        # fix and insert under the uploader
beeplay-ops import ~/game --owner beeplay --title … --category … --emoji 🎮
beeplay-ops import ~/qa --owner beeplay … --unlisted  # test game, link only
beeplay-ops replace 12 ~/fixed    # new version; a hidden game comes back live
beeplay-ops status 12 live        # also: hidden, unlisted, deleted
beeplay-ops health 12             # plays and errors in the crash window
beeplay-ops history 12            # full audit trail
```

A game is hidden automatically when at least 3 plays in 30 minutes failed and
failures are at least half of the plays. A play fails if the game has not
loaded after 10 s, or throws in its first 30 s. The thresholds are in
`/etc/beeplay/beeplay.env`. Crash reports are unauthenticated: if fake reports
hide a good game, `beeplay-ops status <id> live`.

Tracing one game or one uploader:

```bash
grep '"work_id": 12' /var/lib/beeplay/logs/events.jsonl
grep '"slug": "bee-3"' /var/lib/beeplay/logs/events.jsonl
journalctl -u beeplay -o cat | grep auto_hidden
```

## Alerts

New uploads, failed uploads and auto-hidden games post to a Feishu webhook
once `BEEPLAY_ALERT_WEBHOOK` in `/etc/beeplay/beeplay.env` is set, then
`systemctl restart beeplay`. Until then alerts only reach the logs. The
lark-cli app bot cannot post to the external 🐝蜂玩BeePlay group; add a custom
bot in that group's settings and paste its webhook URL.

## Tester identities

Claims release two hours after a tester's last request. To free them all
before a demo round:

```bash
sudo -u beeplay sqlite3 /var/lib/beeplay/beeplay.db \
  "UPDATE users SET last_seen_at = NULL, claim_token = NULL;"
```
