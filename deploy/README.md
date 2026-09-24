# Deploying Beeplay

Caddy owns ports 80 and 443 for the shared host. It serves BeePlay's
`/assets/` and `/games/` from disk and proxies everything else to uvicorn on
`127.0.0.1:8000`. The canonical site is `https://beeplay.top/` (ssh alias
`evotavern`). Session cookies are Secure; direct HTTP and unrecognized hosts do
not serve the application.

## One-time nginx-to-Caddy migration

The existing host also serves Moonanswer. Its current Caddy site and global
options must remain intact. After DNS for `beeplay.top` and `www.beeplay.top`
points to `47.251.140.176`, copy this checkout to the server and run:

```bash
sudo bash deploy/setup-caddy.sh
```

The script backs up `/etc/caddy/Caddyfile`, splits Moonanswer into
`/etc/caddy/sites/moonanswer.caddy`, installs the BeePlay fragment, validates
the combined configuration, removes the insecure claim-cookie override, then
switches the public edge from nginx to Caddy. If validation or Caddy startup
fails, it restores the previous Caddy configuration and re-enables nginx.
Existing HTTP claim cookies must be claimed again after the cutover.

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
- syncs code, installs dependencies, the systemd unit, the BeePlay Caddy site and
  `/usr/local/bin/beeplay-ops`
- stops the app, migrates the schema (`beeplay-ops migrate`), gives every
  game the current reporter and sandbox shim (`beeplay-ops refresh-reporter`;
  a changed `assets/js/game-reporter.js` republishes each game under a new
  artifact, hidden games stay hidden), starts the app
- waits for HTTP 200 and prints rollback commands if it never comes

Schema changes are Alembic migrations in `migrations/versions/`. The app also
migrates on startup, so a plain restart is always safe.

## First install on a new server

```bash
sudo apt-get update && sudo apt-get install -y curl sqlite3 rsync nodejs
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
sudo useradd --system --home /srv/beeplay --shell /usr/sbin/nologin beeplay
sudo mkdir -p /srv/beeplay && sudo chown beeplay:beeplay /srv/beeplay
```

Install Caddy with the Cloudflare DNS module required by the shared
Moonanswer configuration, create `/etc/caddy/cloudflare.env`, then run
`deploy/push.sh` followed by `deploy/setup-caddy.sh`. Enable `beeplay` and
open TCP ports 80 and 443 in the cloud firewall.

## State

Everything lives in `/var/lib/beeplay`:

| Path | What |
|------|------|
| `beeplay.db` | SQLite: users, works (with `status`), `work_events`, `health_events`, `failed_uploads` |
| `games/<artifact>/` | one directory per uploaded version; replaced versions stay |
| `failed/<id>.zip` | uploads that failed validation, waiting for an operator |
| `avatars/<hash>.webp` | profile photos, re-encoded; Caddy serves them as `/avatars/` |
| `logs/events.jsonl` | one JSON line per event; the journal has the same lines |
| `logs/ux-last-run` | when `beeplay-ops ux` last ran |
| `logs/person-key` | secret behind the anonymous person ids in the log; keep it private |

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

What players ran into since the last check, by area and then by person:

```bash
beeplay-ops ux                    # since the last check, then records this one
beeplay-ops ux --every 60         # only if the last check is over an hour old
beeplay-ops ux --since 2h --no-mark
```

It reads `http_error` (every 4xx/5xx the app answered), `client_error` (what
the page's own reporter, `assets/js/page-reporter.js`, caught: script errors,
uploads that never reached the app, e.g. a 413 from the edge proxy, and
`shown` reports of the message a failure put on screen) and the crash events
above. Every area (creation, gameplay, other) is listed in full, one entry per
person, with:

- an outcome: `STUCK` (failed more than once, no success since), `NO SUCCESS
  SINCE`, or `RECOVERED` (a `creation_ok` or `play_ok` after the last failure);
  stuck players come first;
- `saw:` what the page showed and whether the player was sent away or lost
  their input, or `saw (inferred):` where the page does not report it yet;
- the account id (`u42`, see `beeplay-ops user`) when there was one; "in-app only" means every report
  came from WeChat, QQ, Douyin or another in-app browser.

A person is `p-` plus a hash of IP and User-Agent keyed with
`/var/lib/beeplay/logs/person-key` and the UTC date: the same player all day,
unlinkable across days, and the IP itself is never logged. Events from before
person ids existed are grouped by browser string, marked as such, and have no
outcome. 404/405s from requests without a BeePlay cookie are scanners: only
their number is shown ("noise hidden").

Tracing one game or one uploader:

```bash
grep '"work_id": 12' /var/lib/beeplay/logs/events.jsonl
grep '"who": "u42"' /var/lib/beeplay/logs/events.jsonl
journalctl -u beeplay -o cat | grep auto_hidden
```

## Alerts

New uploads, failed uploads and auto-hidden games post to a Feishu webhook
once `BEEPLAY_ALERT_WEBHOOK` in `/etc/beeplay/beeplay.env` is set, then
`systemctl restart beeplay`. Until then alerts only reach the logs. The
lark-cli app bot cannot post to the external 🐝蜂玩BeePlay group; add a custom
bot in that group's settings and paste its webhook URL.

## Accounts

Accounts are made silently on a player's first like, save, creation or visit
to their profile; setting a password is what lets them log in elsewhere.
There is no email or phone, so a forgotten password goes through staff:

```bash
beeplay-ops user honey_lab          # or u42, as the ux check prints it
beeplay-ops reset-password honey_lab  # prints a one-time link, valid 24 h
beeplay-ops avatar-remove honey_lab   # back to the default drawing
```

Check it is really them before handing over the link: opening it sets a new
password and signs every device out. An account without a password has
nothing to reset; it exists only in the browser that made it.

## Generated game validation

Node.js is required on the app host for JavaScript syntax validation (code is
compiled, never executed). Releases check for it before changing the running app.
Prompt version 2 assigns a stable, roughly 50/50 2D/3D rendering preference per
job; explicit user preferences take priority. 3D uses projected geometry on
Canvas 2D within the existing offline sandbox. Invalid scripts fail generation;
preview errors/timeouts invalidate the publish gate until a fresh successful preview.
Syntax validation does not prove runtime or gameplay correctness: creators must
still test controls, scoring and restart on their target devices.
