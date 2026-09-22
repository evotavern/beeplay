# Deploying Beeplay with Nginx

This deployment serves Beeplay directly on the server's public IP over HTTP.
Nginx listens on port 80, serves assets and game artifacts from disk, and
proxies application requests to uvicorn on `127.0.0.1:8000`.

For the current server, open `http://47.251.140.176/` after deployment.

## Install

Run these commands on the server from a checkout of this branch:

```bash
# 1. OS packages and service account
sudo apt-get update
sudo apt-get install -y curl nginx
curl -LsSf https://astral.sh/uv/install.sh | sudo env UV_INSTALL_DIR=/usr/local/bin sh
uv --version
sudo useradd --system --home /srv/beeplay --shell /usr/sbin/nologin beeplay

# 2. Application code and dependencies
sudo mkdir -p /srv/beeplay
sudo rsync -a --delete --exclude '.git' --exclude '.venv' --exclude 'beeplay.db*' --exclude 'games' ./ /srv/beeplay/
sudo chown -R beeplay:beeplay /srv/beeplay
sudo chmod -R a+rX /srv/beeplay/assets
sudo -u beeplay uv sync --project /srv/beeplay --frozen

# 3. Application state and the first playable game
sudo install -d -o beeplay -g beeplay /var/lib/beeplay/games
sudo rsync -a /root/beeplay-handoff/af359667cf6a8038/ /var/lib/beeplay/games/af359667cf6a8038/
sudo chown -R beeplay:beeplay /var/lib/beeplay
sudo chmod -R a+rX /var/lib/beeplay/games

# 4. FastAPI application
sudo cp deploy/beeplay.service /etc/systemd/system/beeplay.service
sudo systemctl daemon-reload
sudo systemctl enable --now beeplay.service

# 5. Public Nginx listener
sudo rm -f /etc/nginx/sites-enabled/default
sudo cp deploy/nginx.conf /etc/nginx/sites-available/beeplay
sudo ln -sfn /etc/nginx/sites-available/beeplay /etc/nginx/sites-enabled/beeplay
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

`uv sync` downloads a compatible Python runtime when the host does not
already have one; Beeplay requires Python 3.12 or newer. Ensure the cloud
firewall permits inbound TCP port 80.

The app seeds its own SQLite database at `/var/lib/beeplay/beeplay.db` on
first startup. The handoff game is listed in that seed data, and is rendered
only after its `index.html` exists under `/var/lib/beeplay/games`.

## Verify

```bash
systemctl status beeplay nginx
curl -sI http://127.0.0.1:8000/ | head -1
curl -sI http://127.0.0.1/ | head -1
curl -sI http://127.0.0.1/games/af359667cf6a8038/index.html | head -1
```

## Deploying a change

```bash
sudo rsync -a --delete --exclude '.git' --exclude '.venv' --exclude 'beeplay.db*' --exclude 'games' ./ /srv/beeplay/
sudo chown -R beeplay:beeplay /srv/beeplay
sudo chmod -R a+rX /srv/beeplay/assets
sudo -u beeplay uv sync --project /srv/beeplay --frozen
sudo systemctl restart beeplay.service
sudo nginx -t && sudo systemctl reload nginx
```
