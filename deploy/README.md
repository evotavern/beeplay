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

A person ships a green pull request from a laptop, from any checkout:

```bash
deploy/push.sh 12             # briefing, then type "ship": merges PR #12 and releases it
deploy/push.sh --dry-run 12   # the briefing and the server's checks; nothing changes
deploy/push.sh main           # releases main as it is, e.g. after merging on GitHub
deploy/push.sh rollback       # the previous release back, and a revert PR
deploy/push.sh setup          # once per server: beeplay-release and its deploy key
```

`push.sh` first prints a one-screen briefing: what ships, what is live (and
since when), what changes, a short summary and what to test (written by Claude
from the diff), other open PRs touching the same files, worktrees on this
laptop with unpushed work and the sessions running in them, and errors in prod
since the last release.

- **Hard stops, which nothing overrides** (`rollback` is the way out):
  - the tests failed, are running or never ran (only a warning until CI exists);
  - the PR is behind `main`, based on another PR, a draft, conflicting or closed;
  - `main` does not contain the live commit, so releasing would take back what
    players have;
  - another release is running;
  - what is live can't be told;
  - the server has no deploy key yet.
- **Warnings** you acknowledge by typing `ship`: migrations, dependency or
  server changes, a large diff, overlapping PRs, unpushed work elsewhere, errors
  in prod, or a rollback whose revert has not been merged.

`ship` is read from the terminal, not a pipe, so agents cannot release: they
prepare pull requests and say when one is ready. `push.sh` then merges the PR
with a merge commit (never squash: the checks follow commit ids) and asks the
server to release exactly that commit.

On the server, `beeplay-release` downloads the commit straight from GitHub with
a read-only deploy key, so the laptop's connection to GitHub is not in the way.
It refuses anything that is not on `main` or does not contain the live commit,
one release at a time, writes `version.json` into the release (served, uncached,
at https://beeplay.top/version), logs to `/var/lib/beeplay/logs/releases.jsonl`,
runs that commit's own `deploy/release.sh`, and after a good release posts what
to test to the 🐝蜂玩BeePlay group, in Chinese, for Double. The last three
releases stay in `/var/lib/beeplay-release/releases/`.

`deploy/release.sh`:

- installs `/etc/beeplay/beeplay.env` if missing (never overwrites it)
- **rehearses before touching anything live:** in `/srv/beeplay.next`, the new
  code with its own dependencies migrates a copy of the live database, and the
  new BeePlay Caddy site is validated beside the other sites. If either fails
  the release stops there, with the site untouched.
- backs the database up to `/var/backups/beeplay/beeplay-<time>.db`
- keeps the code that is live at `/srv/beeplay.prev`, if the site serves it
  right now; otherwise the older, working copy stays there
- syncs code with its file modes set on the server (Caddy must be able to read
  everything, whatever the modes of the pushed tree), installs dependencies,
  the systemd units, the BeePlay Caddy site, `/usr/local/bin/beeplay-ops`,
  `beeplay-check`, `beeplay-notify` and `beeplay-release`
- stops the app, migrates the schema (`beeplay-ops migrate`), gives every
  game the current reporter and sandbox shim (`beeplay-ops refresh-reporter`;
  a changed `assets/js/game-reporter.js` republishes each game under a new
  artifact, hidden games stay hidden), starts the app
- checks it the way players reach it: `beeplay-check` loads the page through
  Caddy and every `/assets/` file it uses, which must answer 200 with the
  right type, and makes sure a missing file is not cached
- starts `beeplay-check.timer`, the same check every 5 minutes

If anything fails after the code was swapped, the previous release comes back
by itself: code, systemd unit and Caddy site. When the failed release had
already moved the database to a new schema version, the previous code cannot
run on it, so the backup has to come back too, losing what players wrote since.
The script says how many minutes that is and does it only if you type
`restore`; otherwise the new release stays and it prints the steps to go back
by hand. A failed release is kept at `/srv/beeplay.failed`.

`deploy/push.sh rollback` does the same for the last good release, when a
problem shows up later: the previous code, unit and Caddy site come back, the
database backup too only if that release moved the schema version (and only
after you type `restore`), the group hears it was rolled back, and a revert PR
opens on GitHub so `main` stops carrying the change. The rolled-back release is
kept at `/srv/beeplay.rolled-back`.

If GitHub cannot be reached from the server either, re-run the newest export
by hand: `ssh evotavern`, then
`bash /var/lib/beeplay-release/releases/<newest>/deploy/release.sh`.

Schema changes are Alembic migrations in `migrations/versions/`. The app also
migrates on startup, so a plain restart is always safe.

## First install on a new server

```bash
sudo apt-get update && sudo apt-get install -y curl sqlite3 rsync
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

When beeplay.top breaks and when it recovers, `beeplay-check.timer` posts to
the 🐝蜂玩BeePlay group, in Chinese, through the group's webhook bot. It checks
every 5 minutes, through Caddy on the server, so it catches the app being
down and files Caddy cannot serve, but not DNS or network outages. Set it up
once: in the group, 设置 → 群机器人 → 添加机器人 → 自定义机器人, turn on
签名校验, then add the two values to `/etc/beeplay/beeplay.env` (no restart
needed):

```
BEEPLAY_RELEASE_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/…
BEEPLAY_RELEASE_WEBHOOK_SECRET=…
```

`beeplay-check` on the server runs the check by hand; `beeplay-notify "text"`
posts to the group. `systemctl list-timers beeplay-check.timer` shows when it
last ran; `journalctl -u beeplay-check -n 20` shows what it found.

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
