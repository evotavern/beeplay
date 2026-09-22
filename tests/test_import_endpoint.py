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

from app import main
from app.models import Base, Work


def zip_bundle(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for name, contents in files.items():
            archive.writestr(name, contents)
    return output.getvalue()


class ImportEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_imports_a_zip_into_the_feed_without_an_async_event_loop_handler(self) -> None:
        bundle = UploadFile(
            file=io.BytesIO(zip_bundle({"dist/index.html": "<h1>Game</h1>"})),
            filename="my-game.zip",
        )
        with tempfile.TemporaryDirectory() as directory, patch.object(main, "GAMES_DIR", Path(directory)):
            response = main.import_game(title="My game", bundle=bundle, session=self.session)

            payload = json.loads(response.body)
            game = self.session.scalar(select(Work).where(Work.artifact_hash == payload["artifact"]))
            self.assertEqual(payload["title"], "My game")
            self.assertEqual(game.collection, "feed")
            self.assertTrue((Path(directory) / payload["artifact"] / "index.html").is_file())

        self.assertFalse(inspect.iscoroutinefunction(main.import_game))

    def test_returns_the_existing_validation_error_for_an_invalid_zip(self) -> None:
        bundle = UploadFile(file=io.BytesIO(b"not a zip"), filename="game.zip")
        with tempfile.TemporaryDirectory() as directory, patch.object(main, "GAMES_DIR", Path(directory)):
            with self.assertRaisesRegex(HTTPException, "只能上传 zip"):
                main.import_game(bundle=bundle, session=self.session)
