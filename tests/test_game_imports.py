import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from app.game_imports import (
    REPORTER_MARKER,
    REPORTER_VERSION,
    GameImportError,
    inject_reporter,
    install_folder,
    install_zip,
    pack_zip,
    read_zip,
)


def make_zip(files: dict[str, str]) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        for path, contents in files.items():
            archive.writestr(path, contents)
    return output.getvalue()


class GameImportTests(unittest.TestCase):
    def test_upgrades_the_legacy_reporter_in_place(self) -> None:
        legacy = REPORTER_MARKER + b"<script>oldReporter()</script><main>game</main>"
        upgraded = inject_reporter(legacy)
        self.assertIn(REPORTER_VERSION, upgraded)
        self.assertNotIn(b"oldReporter", upgraded)
        self.assertEqual(upgraded.count(REPORTER_MARKER), 1)
        self.assertIn(b"<main>game</main>", upgraded)

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
