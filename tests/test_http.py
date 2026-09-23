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
from app.models import HealthEvent, Work


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

    def test_discover_shows_its_empty_state(self) -> None:
        self.assertIn("发现页正在酿蜜中", self.client.get("/discover").text)


if __name__ == "__main__":
    unittest.main()
