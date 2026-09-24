"""deploy/beeplay-check and deploy/beeplay-notify, run for real against a
stand-in for beeplay.top and a stand-in for the Lark webhook."""

import base64
import hashlib
import hmac
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "deploy" / "beeplay-check"
NOTIFY = ROOT / "deploy" / "beeplay-notify"

PAGE = (
    '<html><head><link rel="stylesheet" href="/assets/css/app.css?v=1">'
    '<script src="/assets/js/app.js?v=2"></script></head>'
    '<body><img src="/assets/icons/logo.png?v=3" alt=""></body></html>'
)
CACHED = {"Cache-Control": "public, max-age=604800"}


def serve(handler) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Site:
    """Answers like beeplay.top behind Caddy until a test changes a route."""

    def __init__(self) -> None:
        self.page = PAGE
        self.routes = {
            "/": (200, "text/html; charset=utf-8", {}),
            "/assets/css/app.css": (200, "text/css; charset=utf-8", CACHED),
            "/assets/js/app.js": (200, "text/javascript; charset=utf-8", CACHED),
            "/assets/icons/logo.png": (200, "image/png", CACHED),
        }
        self.missing = (404, "text/plain", {})
        site = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                path = self.path.split("?")[0]
                status, content_type, headers = site.routes.get(path, site.missing)
                body = site.page.encode() if path == "/" else b"x"
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                for name, value in headers.items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                pass

        self.server = serve(Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"


class Hook:
    """Records what is posted to it and answers like Lark's webhook."""

    def __init__(self) -> None:
        self.posts: list[dict] = []
        self.answer = {"code": 0, "msg": "success", "data": {}}
        hook = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                hook.posts.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                body = json.dumps(hook.answer).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                pass

        self.server = serve(Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}/open-apis/bot/v2/hook/test"


class Case(unittest.TestCase):
    def setUp(self) -> None:
        self.site = Site()
        self.hook = Hook()
        for server in (self.site.server, self.hook.server):
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.work = Path(work.name)
        # beeplay-check calls beeplay-notify by name, as installed on the server.
        (self.work / "bin").mkdir()
        (self.work / "bin" / "beeplay-notify").symlink_to(NOTIFY)
        self.env = {
            **os.environ,
            "PATH": f"{self.work / 'bin'}{os.pathsep}{os.environ['PATH']}",
            "BEEPLAY_CHECK_URL": self.site.url,
            "BEEPLAY_CHECK_STATE": str(self.work / "check.state"),
            "BEEPLAY_CHECK_RETRY_S": "0",
            "BEEPLAY_ENV_FILE": str(self.work / "no-such.env"),
            "BEEPLAY_RELEASE_WEBHOOK": self.hook.url,
            "BEEPLAY_RELEASE_WEBHOOK_SECRET": "s3cret",
        }

    def check(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["bash", str(CHECK), *args], env=self.env, capture_output=True, text=True, timeout=60
        )


class CheckTests(Case):
    def test_a_healthy_site_passes(self) -> None:
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), f"ok: {self.site.url}/ and 3 files")

    def test_an_unreadable_asset_fails_and_names_it(self) -> None:
        self.site.routes["/assets/js/app.js"] = (403, "text/plain", CACHED)
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout.strip(), f"403 {self.site.url}/assets/js/app.js?v=2")

    def test_an_asset_with_the_wrong_type_fails(self) -> None:
        self.site.routes["/assets/css/app.css"] = (200, "text/html; charset=utf-8", {})
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("app.css?v=1 (expected text/css, got text/html; charset=utf-8)", result.stdout)

    def test_an_error_that_browsers_would_keep_fails(self) -> None:
        self.site.missing = (404, "text/plain", CACHED)
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("(error cached: Cache-Control: public, max-age=604800)", result.stdout)

    def test_files_only_leaves_caching_out(self) -> None:
        self.site.missing = (404, "text/plain", CACHED)
        self.assertEqual(self.check("--files-only").returncode, 0)

    def test_a_page_that_is_down_fails(self) -> None:
        self.site.routes["/"] = (502, "text/plain", {})
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn(f"502 {self.site.url}/ (page: expected 200 text/html", result.stdout)

    def test_a_page_without_assets_fails(self) -> None:
        self.site.page = "<html><body>maintenance</body></html>"
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("the page uses no /assets/ files", result.stdout)

    def test_an_unreachable_site_fails(self) -> None:
        self.site.server.shutdown()
        self.site.server.server_close()
        result = self.check()
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stdout.startswith("000 "), result.stdout)


class AlertTests(Case):
    def assert_signed(self, post: dict) -> None:
        key = f"{post['timestamp']}\ns3cret".encode()
        expected = base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode()
        self.assertEqual(post["sign"], expected)

    def test_lark_hears_once_when_it_breaks_and_once_when_it_recovers(self) -> None:
        self.assertEqual(self.check("--alert").returncode, 0)
        self.assertEqual(self.hook.posts, [])

        self.site.routes["/assets/js/app.js"] = (403, "text/plain", {})
        self.assertEqual(self.check("--alert").returncode, 1)
        self.assertEqual(self.check("--alert").returncode, 1)
        self.assertEqual(len(self.hook.posts), 1)
        broken = self.hook.posts[0]
        self.assertEqual(broken["msg_type"], "text")
        self.assertTrue(broken["content"]["text"].startswith("🔴 beeplay.top 出问题了"))
        self.assertIn("/assets/js/app.js?v=2", broken["content"]["text"])
        self.assert_signed(broken)

        self.site.routes["/assets/js/app.js"] = (200, "text/javascript", CACHED)
        self.assertEqual(self.check("--alert").returncode, 0)
        self.assertEqual(self.check("--alert").returncode, 0)
        self.assertEqual(len(self.hook.posts), 2)
        self.assertEqual(self.hook.posts[1]["content"]["text"], "🟢 beeplay.top 已恢复正常。")
        self.assert_signed(self.hook.posts[1])

    def test_a_refused_message_is_sent_again_on_the_next_run(self) -> None:
        self.site.routes["/"] = (502, "text/plain", {})
        self.hook.answer = {"code": 19021, "msg": "sign match fail or timestamp is not within one hour"}
        self.check("--alert")
        self.hook.answer = {"code": 0, "msg": "success"}
        self.check("--alert")
        self.assertEqual(len(self.hook.posts), 2)
        self.assertEqual((self.work / "check.state").read_text().strip(), "broken")


class NotifyTests(Case):
    def notify(self, *args: str, **env: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(NOTIFY), *args], env={**self.env, **env}, capture_output=True, text=True, timeout=30
        )

    def test_without_a_webhook_the_message_is_only_printed(self) -> None:
        result = self.notify("hello", BEEPLAY_RELEASE_WEBHOOK="")
        self.assertEqual(result.returncode, 0)
        self.assertIn("not set", result.stderr)
        self.assertEqual(self.hook.posts, [])

    def test_without_a_secret_the_message_is_not_signed(self) -> None:
        self.assertEqual(self.notify("你好", BEEPLAY_RELEASE_WEBHOOK_SECRET="").returncode, 0)
        self.assertEqual(self.hook.posts, [{"msg_type": "text", "content": {"text": "你好"}}])

    def test_the_webhook_can_come_from_the_env_file(self) -> None:
        env_file = self.work / "beeplay.env"
        env_file.write_text(f"BEEPLAY_RELEASE_WEBHOOK={self.hook.url}\n")
        env = {k: v for k, v in self.env.items() if not k.startswith("BEEPLAY_RELEASE_WEBHOOK")}
        result = subprocess.run(
            [str(NOTIFY), "from the file"], env={**env, "BEEPLAY_ENV_FILE": str(env_file)},
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.hook.posts[0]["content"]["text"], "from the file")


if __name__ == "__main__":
    unittest.main()
