import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.game_imports import (
    HEAD_API,
    HEAD_MARKER,
    REPORTER_MARKER,
    GameImportError,
    inject_head_api,
    inject_reporter,
    install_folder,
    install_zip,
    pack_zip,
    read_zip,
    reporter_is_current,
)


def make_zip(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path, contents in files.items():
            archive.writestr(path, contents)
    return output.getvalue()


class GameImportTests(unittest.TestCase):
    def test_installs_a_dist_folder_without_changing_its_contents(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = install_folder(
                [
                    ("dist/index.html", b"<script src='assets/game.js'></script>"),
                    ("dist/assets/game.js", b"startGame()"),
                ],
                Path(directory),
            )
            self.assertEqual(
                (Path(directory) / artifact / "assets" / "game.js").read_text(), "startGame()"
            )

    def test_installs_a_zip_with_a_wrapping_folder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = install_zip(
                make_zip({"tetris/index.html": "<canvas></canvas>"}), Path(directory)
            )
            self.assertTrue((Path(directory) / artifact / "index.html").is_file())

    def test_rejects_a_folder_without_an_entry_point(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(GameImportError, "index.html"):
                install_folder([("dist/game.js", b"startGame()")], Path(directory))

    def test_rejects_an_unsafe_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(GameImportError, "不安全"):
                install_folder(
                    [("index.html", b"ok"), ("../outside.txt", b"no")], Path(directory)
                )

    def test_swaps_an_older_reporter_for_the_current_one(self) -> None:
        old = b"<html><head>" + REPORTER_MARKER + b"<script>oldReporter()</script><title>t</title></head></html>"
        new = inject_reporter(old)
        self.assertTrue(reporter_is_current(new))
        self.assertNotIn(b"oldReporter", new)
        self.assertEqual(new.count(REPORTER_MARKER), 1)
        self.assertIn(b"<title>t</title>", new)
        self.assertEqual(inject_reporter(new), new)

    def test_head_api_follows_the_reporter_and_survives_a_reporter_refresh(self) -> None:
        game = inject_head_api(b"<html><head><script>game()</script></head></html>")
        self.assertLess(game.index(REPORTER_MARKER), game.index(HEAD_API))
        self.assertLess(game.index(HEAD_API), game.index(b"game()"))
        self.assertEqual(inject_head_api(game), game)
        older = game.replace(game[game.index(REPORTER_MARKER):game.index(HEAD_API)],
                             REPORTER_MARKER + b"<script>oldReporter()</script>")
        refreshed = inject_reporter(older)
        self.assertTrue(reporter_is_current(refreshed))
        self.assertEqual(refreshed.count(HEAD_API), 1)

    def test_an_older_head_api_counts_as_out_of_date_and_is_swapped(self) -> None:
        game = inject_head_api(b"<html><head><script>game()</script></head></html>")
        older = game.replace(HEAD_API, HEAD_MARKER + b"<script>oldHead()</script>")
        self.assertFalse(reporter_is_current(older))
        refreshed = inject_reporter(older)
        self.assertEqual(refreshed, game)
        self.assertNotIn(b"oldHead", refreshed)

