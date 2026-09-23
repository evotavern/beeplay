"""End-to-end over HTTP: a real app, a real (temporary) database, plain http://."""

import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app import config, db, events, main
from app.models import HealthEvent, Work, WorkLike, WorkSave, WorkShare, WorkView


def game_zip() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr("my-game/index.html", "<html><head></head><canvas></canvas></html>")
    return output.getvalue()


class HttpTests(unittest.TestCase):
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

    def upload(self, **overrides):
        form = {"title": "Block Drop", "category": "brainrot", "emoji": "🧱", "art": "art-two"}
        form.update(overrides)
        return self.client.post(
            "/api/import-game", data=form, files={"bundle": ("game.zip", game_zip(), "application/zip")}
        )

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


if __name__ == "__main__":
    unittest.main()
