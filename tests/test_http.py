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

from app import accounts, config, db, events, identity, main
from app.models import (
    CommentLike, HealthEvent, User, UserFollow, Work, WorkComment,
    WorkLike, WorkSave, WorkShare, WorkView,
)


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
    """A migrated app on a temporary database, over plain http:// like local dev."""

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
            patch.object(config, "AVATARS_DIR", root / "avatars"),
            patch.object(events, "alert"),
            # Local development runs over plain HTTP.
            patch.object(identity, "ALLOW_INSECURE_COOKIES", True),
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

    def sign_up(self, client: TestClient | None = None) -> User:
        """Open /profile, which makes an account for a visitor without one."""
        client = client or self.client
        self.assertEqual(client.get("/profile").status_code, 200)
        return self.current(client)

    def current(self, client: TestClient | None = None) -> User | None:
        token = (client or self.client).cookies.get(accounts.COOKIE_NAME)
        with Session(self.engine) as session:
            return accounts.resolve(session, token)[0]


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

    def test_upload_play_and_crash_over_plain_http(self) -> None:
        # Uploading is one of the things that makes an account.
        self.assertIsNone(self.current())
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

    def test_the_house_account_cannot_log_in_and_owns_the_seed_game(self) -> None:
        with Session(self.engine) as session:
            seed = session.scalar(select(Work).where(Work.artifact_hash == "af359667cf6a8038"))
            self.assertEqual(seed.status, "live")
            self.assertFalse(seed.owner.loginable)
            self.assertEqual(seed.owner.slug, "beeplay")
        self.assertIn("今日咖啡心情", self.client.get("/u/beeplay").text)
        refused = self.client.post("/api/login", json={"handle": "beeplay", "password": "anything"})
        self.assertEqual(refused.status_code, 422)

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

        # Playing and sharing never make an account.
        for _ in range(2):
            view = self.client.post(
                f"/api/works/{work_id}/view", json={"event_id": "anonymous-view-1"}
            )
            self.assertEqual(view.json(), {"count": 1})
            share = self.client.post(
                f"/api/works/{work_id}/share", json={"event_id": "anonymous-share-1"}
            )
            self.assertEqual(share.json(), {"count": 1})
        self.assertIsNone(self.current())

        # The first like does.
        self.assertEqual(
            self.client.post(
                f"/api/works/{work_id}/like", json={"active": True}
            ).json(),
            {"active": True, "count": 1},
        )
        self.assertIsNotNone(self.current())
        self.assertEqual(
            self.client.post(
                f"/api/works/{work_id}/save", json={"active": True}
            ).json(),
            {"active": True},
        )
        self.client.post(
            f"/api/works/{work_id}/view", json={"event_id": "signed-in-view-1"}
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
        self.sign_up()

        for active in (True, True, False, False):
            like = self.client.post(f"/api/works/{work_id}/like", json={"active": active})
            self.assertEqual(like.status_code, 200)
            self.assertEqual(like.json(), {"active": active, "count": int(active)})
            save = self.client.post(f"/api/works/{work_id}/save", json={"active": active})
            self.assertEqual(save.status_code, 200)
            self.assertEqual(save.json(), {"active": active})

    def test_follows_comments_and_comment_likes_persist_for_accounts(self) -> None:
        with Session(self.engine) as session:
            author = accounts.create_account(session)
            work = session.scalar(select(Work).where(Work.artifact_hash == "af359667cf6a8038"))
            work.user_id = author.id
            session.commit()
            author_id, work_id = author.id, work.id
        self.assertEqual(self.client.get(f"/api/works/{work_id}/comments").json(), {"comments": []})
        # The first comment makes the visitor's account, like a first like does.
        created = self.client.post(f"/api/works/{work_id}/comments", json={"content": "  好玩  "})
        self.assertEqual(created.status_code, 201)
        comment = created.json()
        self.assertEqual(comment["content"], "好玩")
        self.assertTrue(comment["avatar"])
        follow = self.client.post(f"/api/users/{author_id}/follow", json={"active": True})
        self.assertEqual(follow.json(), {"active": True})
        liked = self.client.post(f"/api/comments/{comment['id']}/like", json={"active": True})
        self.assertEqual(liked.json(), {"active": True, "count": 1})
        listed = self.client.get(f"/api/works/{work_id}/comments").json()["comments"]
        self.assertEqual(
            (listed[0]["content"], listed[0]["likes"], listed[0]["liked"], listed[0]["handle"]),
            ("好玩", 1, True, comment["handle"]),
        )
        home = self.client.get("/").text
        self.assertIn('class="follow-author following"', home)
        self.assertIn('data-social-count="comments">1</small>', home)
        with Session(self.engine) as session:
            self.assertEqual(session.query(UserFollow).count(), 1)
            self.assertEqual(session.query(WorkComment).count(), 1)
            self.assertEqual(session.query(CommentLike).count(), 1)

    def logged(self, event: str) -> list[dict]:
        if not config.EVENTS_LOG.exists():
            return []
        lines = [json.loads(line) for line in config.EVENTS_LOG.read_text().splitlines()]
        return [line for line in lines if line["event"] == event]

    def test_failed_requests_are_logged_with_the_browser(self) -> None:
        self.client.get("/", headers={"User-Agent": WECHAT})
        self.assertEqual(self.upload(headers={"User-Agent": WECHAT}, title="").status_code, 422)
        self.client.get("/api/works/1/like?token=secret-token")

        errors = self.logged("http_error")
        self.assertEqual(
            [(e["method"], e["path"], e["status"]) for e in errors],
            [("POST", "/api/import-game", 422), ("GET", "/api/works/1/like", 405)],
        )
        self.assertEqual(errors[0]["browser"], "wechat")
        self.assertEqual(errors[0]["ua"], WECHAT)
        self.assertNotIn("secret-token", config.EVENTS_LOG.read_text())

    def test_failures_and_creations_carry_a_person_but_never_the_ip(self) -> None:
        # The test client's IP is "testclient"; a real browser string keeps
        # that name out of the log unless the IP itself is written.
        browser = {"User-Agent": WECHAT}
        self.assertEqual(self.client.get("/.env", headers=browser).status_code, 404)
        user = self.sign_up()
        self.assertEqual(self.upload(headers=browser, title="").status_code, 422)
        self.assertEqual(self.upload(headers=browser).status_code, 200)

        scanner, rejected = self.logged("http_error")
        self.assertFalse(scanner["cookie"])
        self.assertNotIn("who", scanner)
        self.assertTrue(rejected["cookie"])
        self.assertEqual(rejected["who"], f"u{user.id}")
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


class NoMoreClaimsTests(HttpTestCase):
    """Creating needs no picker any more: the account appears on the way."""

    def test_create_buttons_are_always_enabled(self) -> None:
        self.assertNotIn('aria-disabled="true"', self.client.get("/").text)
        self.assertNotIn("/claim", (Path(__file__).parents[1] / "assets" / "js" / "app.js").read_text())
        self.assertNotIn("/claim", (Path(__file__).parents[1] / "assets" / "js" / "generation.js").read_text())

    def test_old_claim_links_land_on_the_profile(self) -> None:
        response = self.client.get("/claim?next=/discover", follow_redirects=False)
        self.assertEqual((response.status_code, response.headers["location"]), (303, "/profile"))

    def test_an_old_claim_cookie_is_cleared_and_means_nothing(self) -> None:
        self.client.cookies.set(accounts.LEGACY_COOKIE_NAME, "bee-2.0123")
        response = self.client.get("/")
        self.assertIn('beeplay_user=""', response.headers.get("set-cookie", ""))
        self.assertIsNone(self.current())

    def test_a_login_never_returns_to_another_site(self) -> None:
        for target in ["https://evil.example/", "//evil.example/", "/\\evil.example/", "/\t/evil.example/", "evil"]:
            with self.subTest(target=target):
                page = self.client.get("/login", params={"next": target}).text
                self.assertIn('data-next="/"', page)


if __name__ == "__main__":
    unittest.main()
