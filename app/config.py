"""Settings read from the environment, shared by the web app and the ops CLI.

Deployed, these come from /etc/beeplay/beeplay.env; locally everything falls
back to paths next to the code.
"""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, default))


# Unpacked games, one directory per artifact.
GAMES_DIR = _path("BEEPLAY_GAMES_DIR", BASE_DIR / "games")
# Raw bundles that failed validation, kept for an operator to fix.
FAILED_DIR = _path("BEEPLAY_FAILED_DIR", BASE_DIR / "failed")
# One JSON line per event; the journal gets the same lines but may rotate.
EVENTS_LOG = _path("BEEPLAY_EVENTS_LOG", BASE_DIR / "logs" / "events.jsonl")

# Feishu custom-bot webhook. Empty means alerts only reach the logs.
ALERT_WEBHOOK = os.environ.get("BEEPLAY_ALERT_WEBHOOK", "")
# Where links in alerts point. Switch to https:// once TLS exists.
PUBLIC_URL = os.environ.get("BEEPLAY_PUBLIC_URL", "http://127.0.0.1:8010").rstrip("/")

# Crash detection. A play fails if the game has not loaded LOAD_TIMEOUT_S
# after mounting, or throws within ERROR_WINDOW_S. A game is hidden once
# CRASH_MIN_FAILURES plays in the last CRASH_WINDOW_MIN minutes failed and
# they are at least CRASH_RATIO of the plays in that window.
LOAD_TIMEOUT_S = int(os.environ.get("BEEPLAY_LOAD_TIMEOUT_S", 10))
ERROR_WINDOW_S = int(os.environ.get("BEEPLAY_ERROR_WINDOW_S", 30))
CRASH_MIN_FAILURES = int(os.environ.get("BEEPLAY_CRASH_MIN_FAILURES", 3))
CRASH_WINDOW_MIN = int(os.environ.get("BEEPLAY_CRASH_WINDOW_MIN", 30))
CRASH_RATIO = float(os.environ.get("BEEPLAY_CRASH_RATIO", 0.5))
