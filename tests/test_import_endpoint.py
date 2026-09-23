import inspect
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException, UploadFile
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import config, ingest, main
from app.models import Base, FailedUpload, User, Work

DETAILS = dict(title="My game", category="brainrot", emoji="🧱", art="art-two", description="")


def zip_bundle(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    return output.getvalue()


def upload(contents: bytes, name: str = "game.zip") -> UploadFile:
    return UploadFile(file=io.BytesIO(contents), filename=name)


class ImportEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.user = User(
            slug="bee-2", name="小蜜蜂", handle="@b", bio="", avatar_fill="fff",
            saved_count=0, level=1, xp=0, xp_goal=1, position=0,
        )
        self.session.add(self.user)
        self.session.commit()
        self.directory = tempfile.TemporaryDirectory()
        root = Path(self.directory.name)
        self.patches = [
            patch.object(config, "GAMES_DIR", root / "games"),
            patch.object(config, "FAILED_DIR", root / "failed"),
            patch.object(config, "EVENTS_LOG", root / "events.jsonl"),
            patch.object(ingest.events, "alert"),
        ]
        for active in self.patches:
            active.start()

    def tearDown(self) -> None:
        for active in self.patches:
            active.stop()
        self.session.close()
        self.engine.dispose()
        self.directory.cleanup()

    def call(self, identity=None, **fields):
        # Called directly, so FastAPI's File()/Form() defaults must be overridden.
        return main.import_game(
            **{"bundle": None, "files": None, "paths": None, **DETAILS, **fields},
            session=self.session,
            identity=identity or (self.user, "ok"),
        )

    def test_publishes_a_zip_live_under_the_uploader(self) -> None:
        response = self.call(bundle=upload(zip_bundle({"dist/index.html": "<h1>Game</h1>"})))

        payload = json.loads(response.body)
        game = self.session.scalar(select(Work).where(Work.artifact_hash == payload["artifact"]))
        self.assertEqual((game.title, game.status, game.user_id), ("My game", "live", self.user.id))
        self.assertTrue((config.GAMES_DIR / payload["artifact"] / "index.html").is_file())
        self.assertFalse(inspect.iscoroutinefunction(main.import_game))

    def test_publishes_a_folder(self) -> None:
        response = self.call(
            files=[upload(b"<h1>Game</h1>", "index.html")], paths=["dist/index.html"]
        )
        self.assertEqual(json.loads(response.body)["title"], "My game")

    def test_a_broken_zip_is_kept_and_the_uploader_is_sent_to_staff(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self.call(bundle=upload(b"not a zip"))

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIn("工作人员", raised.exception.detail)
        failed = self.session.scalar(select(FailedUpload))
        self.assertEqual(Path(failed.stored_path).read_bytes(), b"not a zip")
        self.assertIn("zip", failed.error)
        self.assertIsNone(self.session.scalar(select(Work)))

    def test_a_broken_folder_is_kept_as_a_zip(self) -> None:
        with self.assertRaises(HTTPException):
            self.call(files=[upload(b"go()", "game.js")], paths=["dist/game.js"])

        failed = self.session.scalar(select(FailedUpload))
        with zipfile.ZipFile(failed.stored_path) as archive:
            self.assertEqual(archive.namelist(), ["dist/game.js"])

    def test_missing_details_are_a_plain_form_error_and_nothing_is_kept(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self.call(bundle=upload(zip_bundle({"index.html": "x"})), title=" ")

        self.assertEqual(raised.exception.status_code, 422)
        self.assertIsNone(self.session.scalar(select(FailedUpload)))

    def test_an_unclaimed_visitor_is_sent_to_claim_an_identity(self) -> None:
        with self.assertRaises(HTTPException) as raised:
            self.call(identity=(None, "anonymous"), bundle=upload(zip_bundle({"index.html": "x"})))

        self.assertEqual(raised.exception.status_code, 401)


if __name__ == "__main__":
    unittest.main()
