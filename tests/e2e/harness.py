"""A throwaway BeePlay with four games, and browsers to drive it.

    uv run --with playwright playwright install --with-deps chromium webkit
    uv run --with playwright python -m unittest discover -s tests/e2e

Not part of the unit suite: tests/e2e has no __init__.py, so `unittest
discover -s tests` never collects it. Each engine that cannot start is skipped,
as is everything when Playwright is missing. E2E_WEBKIT_EXECUTABLE replaces
WebKit's launcher, e.g. with a wrapper that adds host libraries.
"""

import contextlib
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - depends on the machine
    sync_playwright = None

ROOT = Path(__file__).resolve().parents[2]
LIME = "rgb(181, 214, 90)"

SETUPS = {
    # What the reports came from: an iPhone, and a MacBook browser window,
    # where the site still shows the phone layout.
    "iphone": dict(
        viewport={"width": 390, "height": 844}, device_scale_factor=3, is_mobile=True, has_touch=True,
        user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.7 Mobile/15E148 Safari/604.1",
    ),
    "macbook": dict(viewport={"width": 1440, "height": 900}, device_scale_factor=2),
}

GAME = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>html,body{{margin:0;height:100%;background:{color};touch-action:none}}</style>
</head><body></body></html>
"""
# Newest first in the feed. The newest has the tallest tray: another player's
# game (a follow button) with a description long enough for two lines.
GAMES = [
    ("maker", "Tall Tray", "#8e24aa", "A description long enough to wrap onto a second line in the tray, "
     "and then some more words so it is clamped rather than short."),
    ("beeplay", "Green", "#43a047", ""),
    ("beeplay", "Red", "#e53935", ""),
    ("beeplay", "Blue", "#1e88e5", ""),
]


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Server:
    """uvicorn on a free port, over a fresh database and games directory."""

    def __init__(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="beeplay-e2e-"))
        self.port = _free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self.env = dict(
            os.environ,
            BEEPLAY_DB_PATH=str(self.dir / "beeplay.db"),
            BEEPLAY_GAMES_DIR=str(self.dir / "games"),
            BEEPLAY_FAILED_DIR=str(self.dir / "failed"),
            BEEPLAY_EVENTS_LOG=str(self.dir / "logs" / "events.jsonl"),
            BEEPLAY_AVATARS_DIR=str(self.dir / "avatars"),
            BEEPLAY_ALLOW_INSECURE_CLAIMS="1",
        )
        self.process = None

    def _python(self, code: str, *args: str) -> None:
        subprocess.run([sys.executable, "-c", code, *args], cwd=ROOT, env=self.env, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def start(self) -> "Server":
        ops = "from app.ops import main; main()"
        self._python(ops, "migrate")
        self._python(
            "from app import accounts, db\n"
            "with db.SessionLocal() as s:\n"
            "    u = accounts.create_account(s); u.slug = 'maker'; u.name = 'Maker'; s.commit()"
        )
        for owner, title, color, description in reversed(GAMES):
            source = self.dir / "src" / title
            source.mkdir(parents=True)
            (source / "index.html").write_text(GAME.format(title=title, color=color))
            extra = ["--description", description] if description else []
            self._python(ops, "import", str(source), "--owner", owner, "--title", title,
                         "--category", "relax", "--emoji", "🎮", *extra)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(self.port)],
            cwd=ROOT, env=self.env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            with contextlib.suppress(OSError):
                urllib.request.urlopen(self.url + "/", timeout=2).close()
                return self
            time.sleep(0.2)
        self.stop()
        raise RuntimeError("the e2e server did not start")

    def stop(self) -> None:
        if self.process:
            self.process.terminate()
            self.process.wait(timeout=10)
        shutil.rmtree(self.dir, ignore_errors=True)


class Browsers:
    """One Playwright, one browser per engine, a fresh context per page."""

    def __init__(self) -> None:
        if sync_playwright is None:
            raise unittest.SkipTest("playwright is not installed")
        self.playwright = sync_playwright().start()
        self.browsers = {}
        for engine in ("chromium", "webkit"):
            options = {}
            if engine == "webkit" and os.environ.get("E2E_WEBKIT_EXECUTABLE"):
                options["executable_path"] = os.environ["E2E_WEBKIT_EXECUTABLE"]
            try:
                self.browsers[engine] = getattr(self.playwright, engine).launch(**options)
            except Exception as error:  # a missing browser or host library
                print(f"e2e: {engine} unavailable: {str(error).splitlines()[0]}", file=sys.stderr)
        if not self.browsers:
            self.close()
            raise unittest.SkipTest("no browser could start")

    @contextlib.contextmanager
    def page(self, engine: str, setup: str, url: str):
        context = self.browsers[engine].new_context(**SETUPS[setup])
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(url)
        page.wait_for_selector(".game-card.active-game", timeout=10_000)
        try:
            yield page
            if errors:
                raise AssertionError(f"script errors on the page: {errors}")
        finally:
            context.close()

    def close(self) -> None:
        for browser in self.browsers.values():
            browser.close()
        self.playwright.stop()


def active_game(page) -> int:
    return page.evaluate(
        "[...document.querySelectorAll('.game-card')].findIndex(c => c.classList.contains('active-game'))"
    )


def tap(page, setup: str, locator) -> None:
    if SETUPS[setup].get("has_touch"):
        locator.tap()
    else:
        locator.click()
