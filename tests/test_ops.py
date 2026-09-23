import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app import config, db, events, ingest, ops
from app.game_imports import REPORTER_MARKER, pack_zip
from app.models import FailedUpload, User, Work, WorkEvent


class OpsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.engine = create_engine(f"sqlite:///{self.root / 'test.db'}")
        db.migrate(self.engine)
        sessions = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.patches = [
            patch.object(db, "SessionLocal", sessions),
            patch.object(config, "GAMES_DIR", self.root / "games"),
            patch.object(config, "FAILED_DIR", self.root / "failed"),
            patch.object(config, "EVENTS_LOG", self.root / "events.jsonl"),
            patch.object(events, "alert"),
            patch.dict("os.environ", {"SUDO_USER": "vitto"}),
        ]
        for active in self.patches:
            active.start()
        with Session(self.engine) as session:
            session.add(User(
                slug="bee-2", name="小蜜蜂", handle="@b", bio="", avatar_fill="fff",
                saved_count=0, level=1, xp=0, xp_goal=1, position=0,
            ))
            session.commit()
        self.game = self.root / "fixed-game"
        self.game.mkdir()
        (self.game / "index.html").write_text("<html><head></head><canvas></canvas></html>")
        (self.game / "js").mkdir()
        (self.game / "js" / "main.js").write_text("go()")

    def tearDown(self) -> None:
        for active in self.patches:
            active.stop()
        self.engine.dispose()
        self.directory.cleanup()

    def run_ops(self, *argv: str) -> str:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = ops.main(list(argv))
        self.assertEqual(code, 0, output.getvalue())
        return output.getvalue()

    def session(self) -> Session:
        return Session(self.engine)

    def test_import_a_folder_for_a_user(self) -> None:
        self.run_ops(
            "import", str(self.game), "--owner", "bee-2", "--title", "Fixed",
            "--category", "puzzle", "--emoji", "🧩", "--art", "art-three",
        )
        with self.session() as session:
            work = session.scalar(select(Work))
            self.assertEqual((work.title, work.status), ("Fixed", "live"))
            self.assertTrue((config.GAMES_DIR / work.artifact_hash / "js" / "main.js").is_file())
            actor = session.scalar(select(WorkEvent.actor))
        self.assertEqual(actor, "ops:vitto")

    def test_import_unlisted_test_game(self) -> None:
        self.run_ops(
            "import", str(self.game), "--owner", "bee-2", "--title", "QA",
            "--category", "test", "--emoji", "🧪", "--unlisted",
        )
        with self.session() as session:
            self.assertEqual(session.scalar(select(Work.status)), "unlisted")

    def test_fix_and_insert_a_failed_upload_keeps_the_uploaders_details(self) -> None:
        with self.session() as session:
            user = session.scalar(select(User))
            details = ingest.validate_details(
                title="Broken Drop", category="chaos", emoji="🔥", art="art-four", description="hi"
            )
            failed = ingest.capture_failure(
                session, owner=user, details=details, raw_zip=pack_zip([("game.js", b"x")]),
                error="游戏需要包含 index.html",
            )

        self.run_ops("import", str(self.game), "--from-failed", str(failed.id))

        with self.session() as session:
            work = session.scalar(select(Work))
            self.assertEqual((work.title, work.category, work.emoji, work.description),
                             ("Broken Drop", "chaos", "🔥", "hi"))
            self.assertEqual(work.user_id, session.scalar(select(User.id)))
            self.assertEqual(session.get(FailedUpload, failed.id).resolved_work_id, work.id)
        self.assertNotIn("Broken Drop", self.run_ops("failed"))

    def test_replace_status_health_and_history(self) -> None:
        self.run_ops(
            "import", str(self.game), "--owner", "bee-2", "--title", "G",
            "--category", "c", "--emoji", "🎮",
        )
        with self.session() as session:
            work_id = session.scalar(select(Work.id))

        self.run_ops("status", str(work_id), "hidden")
        self.run_ops("replace", str(work_id), str(self.game))
        self.assertIn("plays", self.run_ops("health", str(work_id)))
        history = self.run_ops("history", str(work_id))

        for kind in ("created", "status_changed", "artifact_replaced"):
            self.assertIn(kind, history)
        with self.session() as session:
            self.assertEqual(session.get(Work, work_id).status, "live")
        self.assertIn(str(work_id), self.run_ops("list"))

    def test_refresh_reporter_republishes_games_installed_without_it(self) -> None:
        legacy = config.GAMES_DIR / "af359667cf6a8038"
        legacy.mkdir(parents=True)
        (legacy / "index.html").write_text("<html><head></head></html>")
        with self.session() as session:
            session.add(Work(
                title="Coffee", author="MOOD CAFÉ", category="relax", emoji="☕", art="art-one",
                views="0", likes="0", collection="feed", artifact_hash="af359667cf6a8038",
            ))
            session.commit()

        self.run_ops("refresh-reporter")
        self.run_ops("refresh-reporter")  # idempotent

        with self.session() as session:
            work = session.scalar(select(Work))
            replaced = session.scalars(select(WorkEvent).where(WorkEvent.kind == "artifact_replaced")).all()
        self.assertNotEqual(work.artifact_hash, "af359667cf6a8038")
        self.assertIn(REPORTER_MARKER, (config.GAMES_DIR / work.artifact_hash / "index.html").read_bytes())
        self.assertTrue((legacy / "index.html").is_file())
        self.assertEqual(len(replaced), 1)


if __name__ == "__main__":
    unittest.main()
