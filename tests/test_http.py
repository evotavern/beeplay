"""End-to-end over HTTP: a real app, a real (temporary) database, plain http://."""

import io
import json
import os
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app import config, db, events, main
from app.models import HealthEvent, Work, WorkLike, WorkSave, WorkShare, WorkView


WECHAT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.78(0x18004e2e) NetType/WIFI Language/zh_CN"
)


def game_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("my-game/index.html", "<html><head></head><canvas></canvas></html>")
    return output.getvalue()


class HttpTestCase(unittest.TestCase):
    """A migrated app on a temporary database, with a claimable test client."""

    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.engine = create_engine(f"sqlite:///{root / 'test.db'}")
        sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.patches = [
            patch.object(db, "engine", self.engine),
            patch.object(db, "SessionLocal", sessions),
            patch.object(config, "GAMES_DIR", root / "games"),
            patch.object(config, "FAILED_DIR", root / "failed"),
            patch.object(config, "EVENTS_LOG", root / "events.jsonl"),
            patch.object(events, "alert"),
            # The deployment runs over plain HTTP for now.
            patch.object(main, "ALLOW_INSECURE_CLAIMS", True),
        ]
        for active in self.patches:
            active.start()
        self.client = TestClient(main.app, base_url="http://testserver")
        self.client.__enter__()  # runs the lifespan: migrate and seed

    def tearDown(self) -> None:
        self.client.__exit__(None, None, None)
        for active in self.patches:
            active.stop()
        self.engine.dispose()
        self.directory.cleanup()

    def claim(self, slug: str = "bee-2") -> None:
        self.client.get("/claim")
        token = self.client.cookies.get(main.CSRF_COOKIE_NAME)
        response = self.client.post(f"/claim/{slug}?csrf_token={token}", follow_redirects=False)
        self.assertEqual(response.status_code, 303)



class HttpTests(HttpTestCase):
    def upload(self, headers: dict | None = None, **overrides):
        form = {"title": "Block Drop", "category": "brainrot", "emoji": "🧱", "art": "art-two"}
        form.update(overrides)
        return self.client.post(
            "/api/import-game", data=form, headers=headers,
            files={"bundle": ("game.zip", game_zip(), "application/zip")},
        )

    def test_game_files_are_sandboxed_and_fetchable_from_the_sandbox(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "index.html").write_text("<canvas></canvas>")
            games = FastAPI()
            games.mount("/games", main.GameFiles(directory=directory))
            served = TestClient(games).get("/games/index.html")
        self.assertEqual(served.headers["content-security-policy"], "sandbox allow-scripts")
        # The sandbox's opaque origin loads the game's own files as Origin: null.
        self.assertEqual(served.headers["access-control-allow-origin"], "*")

    def test_claim_upload_play_and_crash_over_plain_http(self) -> None:
        self.assertEqual(self.upload().status_code, 401)

        self.claim()
        response = self.upload()
        self.assertEqual(response.status_code, 200, response.text)
        artifact = response.json()["artifact"]

        home = self.client.get("/").text
        self.assertLess(home.index(artifact), home.index("af359667cf6a8038"))  # newest first
        self.assertIn("Block Drop", self.client.get("/profile").text)
        self.assertIn(b"beeplay-reporter", (config.GAMES_DIR / artifact / "index.html").read_bytes())

        for play in "abc":
            for kind in ("start", "timeout"):
                reply = self.client.post(
                    "/api/game-health",
                    json={"artifact": artifact, "session": play, "kind": kind, "elapsed_ms": 10_000},
                )
                self.assertEqual(reply.status_code, 204)

        self.assertNotIn(artifact, self.client.get("/").text)
        self.assertIn("找黑客松工作人员", self.client.get("/profile").text)
        with Session(self.engine) as session:
            self.assertEqual(session.scalar(select(Work.status).where(Work.artifact_hash == artifact)), "hidden")
            self.assertEqual(len(session.scalars(select(HealthEvent)).all()), 6)

    def test_the_house_account_is_not_offered_and_owns_the_seed_game(self) -> None:
        self.assertNotIn("/claim/beeplay", self.client.get("/claim").text)
        with Session(self.engine) as session:
            seed = session.scalar(select(Work).where(Work.artifact_hash == "af359667cf6a8038"))
            self.assertEqual(seed.status, "live")
            self.assertIsNotNone(seed.user_id)

    def test_discover_uses_real_games_and_zeroed_counts(self) -> None:
        page = self.client.get("/discover").text
        self.assertIn("今日咖啡心情", page)
        self.assertIn("◉ 0", page)
        self.assertNotIn("8.4K", page)

    def test_social_state_is_real_idempotent_and_identity_aware(self) -> None:
        with Session(self.engine) as session:
            work_id = session.scalar(
                select(Work.id).where(Work.artifact_hash == "af359667cf6a8038")
            )

        self.assertEqual(
            self.client.post(f"/api/works/{work_id}/like", json={"active": True}).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(f"/api/works/{work_id}/save", json={"active": True}).status_code,
            401,
        )
        for _ in range(2):
            view = self.client.post(
                f"/api/works/{work_id}/view", json={"event_id": "anonymous-view-1"}
            )
            self.assertEqual(view.json(), {"count": 1})
            share = self.client.post(
                f"/api/works/{work_id}/share", json={"event_id": "anonymous-share-1"}
            )
            self.assertEqual(share.json(), {"count": 1})

        self.claim()
        self.assertEqual(
            self.client.post(
                f"/api/works/{work_id}/like", json={"active": True}
            ).json(),
            {"active": True, "count": 1},
        )
        self.assertEqual(
            self.client.post(
                f"/api/works/{work_id}/save", json={"active": True}
            ).json(),
            {"active": True},
        )
        self.client.post(
            f"/api/works/{work_id}/view", json={"event_id": "claimed-view-1"}
        )

        home = self.client.get("/").text
        self.assertIn('data-game-action="like" aria-pressed="true"', home)
        self.assertIn("今日咖啡心情", self.client.get("/profile?tab=likes").text)
        self.assertIn("今日咖啡心情", self.client.get("/profile?tab=saved").text)
        self.assertIn("今日咖啡心情", self.client.get("/profile?tab=history").text)

        with Session(self.engine) as session:
            self.assertEqual(session.query(WorkLike).count(), 1)
            self.assertEqual(session.query(WorkSave).count(), 1)
            self.assertEqual(session.query(WorkView).count(), 2)
            self.assertEqual(session.query(WorkShare).count(), 1)

        self.client.post(f"/api/works/{work_id}/like", json={"active": False})
        self.client.post(f"/api/works/{work_id}/save", json={"active": False})
        with Session(self.engine) as session:
            self.assertEqual(session.query(WorkLike).count(), 0)
            self.assertEqual(session.query(WorkSave).count(), 0)

    def test_repeated_like_and_save_requests_are_idempotent(self) -> None:
        with Session(self.engine) as session:
            work_id = session.scalar(
                select(Work.id).where(Work.artifact_hash == "af359667cf6a8038")
            )
        self.claim()

        for active in (True, True, False, False):
            like = self.client.post(f"/api/works/{work_id}/like", json={"active": active})
            self.assertEqual(like.status_code, 200)
            self.assertEqual(like.json(), {"active": active, "count": int(active)})
            save = self.client.post(f"/api/works/{work_id}/save", json={"active": active})
            self.assertEqual(save.status_code, 200)
            self.assertEqual(save.json(), {"active": active})

    def logged(self, event: str) -> list[dict]:
        if not config.EVENTS_LOG.exists():
            return []
        lines = [json.loads(line) for line in config.EVENTS_LOG.read_text().splitlines()]
        return [line for line in lines if line["event"] == event]

    def test_failed_requests_are_logged_with_the_browser(self) -> None:
        self.client.get("/", headers={"User-Agent": WECHAT})
        self.assertEqual(self.upload(headers={"User-Agent": WECHAT}).status_code, 401)
        self.client.post("/claim/bee-2?csrf_token=secret-token", follow_redirects=False)

        errors = self.logged("http_error")
        self.assertEqual(
            [(e["method"], e["path"], e["status"]) for e in errors],
            [("POST", "/api/import-game", 401), ("POST", "/claim/bee-2", 403)],
        )
        self.assertEqual(errors[0]["browser"], "wechat")
        self.assertEqual(errors[0]["ua"], WECHAT)
        self.assertNotIn("secret-token", config.EVENTS_LOG.read_text())

    def test_failures_and_creations_carry_a_person_but_never_the_ip(self) -> None:
        # The test client's IP is "testclient"; a real browser string keeps
        # that name out of the log unless the IP itself is written.
        browser = {"User-Agent": WECHAT}
        self.assertEqual(self.client.get("/.env", headers=browser).status_code, 404)
        self.claim()
        self.assertEqual(self.upload(headers=browser, title="").status_code, 422)
        self.assertEqual(self.upload(headers=browser).status_code, 200)

        scanner, rejected = self.logged("http_error")
        self.assertFalse(scanner["cookie"])
        self.assertNotIn("who", scanner)
        self.assertTrue(rejected["cookie"])
        self.assertEqual(rejected["who"], "bee-2")
        [created] = self.logged("creation_ok")
        self.assertEqual(created["path"], "/api/import-game")
        self.assertRegex(created["person"], r"^p-[0-9a-f]{8}$")
        self.assertEqual({scanner["person"], rejected["person"], created["person"]}, {created["person"]})
        self.assertNotIn("testclient", config.EVENTS_LOG.read_text())

    def test_the_message_a_failure_showed_is_logged_for_the_check(self) -> None:
        reply = self.client.post("/api/client-error", json={
            "kind": "shown", "message": "先认领一个身份，再上传游戏吧", "page": "/",
            "area": "creation", "next": "redirected", "lost": True, "status": 401,
        })
        self.assertEqual(reply.status_code, 204)
        [shown] = self.logged("client_error")
        self.assertEqual(
            (shown["kind"], shown["area"], shown["next"], shown["lost"], shown["status"]),
            ("shown", "creation", "redirected", True, 401),
        )
        self.assertIn("person", shown)

    def test_a_game_that_loads_is_logged_as_a_play_for_the_player(self) -> None:
        for kind in ("start", "loaded"):
            reply = self.client.post("/api/game-health", json={
                "artifact": "af359667cf6a8038", "session": "play-1", "kind": kind,
            })
            self.assertEqual(reply.status_code, 204)
        [play] = self.logged("play_ok")
        self.assertIn("person", play)
        self.assertIsNotNone(play["work_id"])

    def test_a_crashing_request_is_logged_as_a_500(self) -> None:
        crashing = TestClient(main.app, raise_server_exceptions=False)
        with patch.object(main, "feed_games", side_effect=RuntimeError("boom")):
            self.assertEqual(crashing.get("/").status_code, 500)

        [error] = self.logged("http_error")
        self.assertEqual((error["path"], error["status"]), ("/", 500))
        self.assertIn("boom", error["error"])

    def test_client_errors_are_logged_with_the_browser(self) -> None:
        reply = self.client.post(
            "/api/client-error",
            headers={"User-Agent": WECHAT},
            json={"kind": "upload", "message": "网络断开了", "page": "/create"},
        )
        self.assertEqual(reply.status_code, 204)

        [error] = self.logged("client_error")
        self.assertEqual((error["kind"], error["message"], error["page"]), ("upload", "网络断开了", "/create"))
        self.assertEqual(error["browser"], "wechat")

    def test_rate_limited_client_errors_are_dropped_without_logging_a_429(self) -> None:
        with patch.object(events.client_error_limiter, "allow", return_value=False):
            reply = self.client.post(
                "/api/client-error", json={"kind": "error", "message": "flood"}
            )

        self.assertEqual(reply.status_code, 204)
        self.assertEqual(self.logged("client_error"), [])
        self.assertEqual(self.logged("http_error"), [])

    def test_client_error_kinds_are_checked(self) -> None:
        reply = self.client.post("/api/client-error", json={"kind": "made-up", "message": "x"})
        self.assertEqual(reply.status_code, 422)
        self.assertEqual(self.logged("client_error"), [])

    def test_crash_reports_carry_the_browser(self) -> None:
        for kind in ("start", "error"):
            self.client.post(
                "/api/game-health",
                headers={"User-Agent": WECHAT},
                json={"artifact": "af359667cf6a8038", "session": "p", "kind": kind, "elapsed_ms": 500},
            )
        [failure] = self.logged("health_fail")
        self.assertEqual(failure["browser"], "wechat")
        self.assertEqual(failure["ua"], WECHAT)


class ClaimBeforeCreateTests(HttpTestCase):
    """Creating needs an identity, so the page says so before any work is done."""

    def claim_with_next(self, slug: str, target: str, client: TestClient | None = None):
        client = client or self.client
        client.get("/claim")
        token = client.cookies.get(main.CSRF_COOKIE_NAME)
        return client.post(
            f"/claim/{slug}", params={"csrf_token": token, "next": target}, follow_redirects=False
        )

    def test_create_buttons_are_disabled_until_an_identity_is_claimed(self) -> None:
        disabled = re.compile(r'<button [^>]*data-action="create"[^>]*aria-disabled="true"')
        self.assertEqual(len(disabled.findall(self.client.get("/").text)), 2)
        self.claim()
        self.assertEqual(disabled.findall(self.client.get("/").text), [])

    def test_the_picker_carries_where_to_return_into_each_claim(self) -> None:
        page = self.client.get("/claim", params={"next": "/discover?create=1"}).text
        self.assertIn("&amp;next=/discover%3Fcreate%3D1", page)

    def test_a_claim_returns_to_the_page_it_was_started_from(self) -> None:
        response = self.claim_with_next("bee-2", "/discover?create=1")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/discover?create=1")

    def test_a_claim_never_returns_to_another_site(self) -> None:
        for target in ["https://evil.example/", "//evil.example/", "/\\evil.example/", "/\t/evil.example/", "evil"]:
            with self.subTest(target=target):
                response = self.claim_with_next("bee-2", target)
                self.assertEqual(response.headers["location"], "/")

    def test_a_lost_race_keeps_the_way_back(self) -> None:
        self.claim("bee-2")
        other = TestClient(main.app, base_url="http://testserver")
        response = self.claim_with_next("bee-2", "/?create=1", client=other)
        self.assertEqual(response.headers["location"], "/claim?notice=taken&next=/%3Fcreate%3D1")

    def test_the_create_click_explains_instead_of_opening_the_modal(self) -> None:
        script = (Path(__file__).parents[1] / "assets" / "js" / "app.js").read_text()
        self.assertIn('if (createButton.getAttribute("aria-disabled") === "true") promptClaim();', script)
        self.assertIn('"/claim?next=" + encodeURIComponent(back.pathname + back.search)', script)
        self.assertIn("resumeCreate();", script)


if __name__ == "__main__":
    unittest.main()
