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
                level=1, xp=0, xp_goal=1, position=0,
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

    def test_viewport_mode_is_audited(self) -> None:
        self.run_ops(
            "import", str(self.game), "--owner", "bee-2", "--title", "Tall",
            "--category", "puzzle", "--emoji", "🎮",
        )
        self.run_ops("viewport", "1", "scroll")
        with self.session() as session:
            work = session.get(Work, 1)
            event = session.scalar(
                select(WorkEvent).where(WorkEvent.kind == "viewport_mode_changed")
            )
            self.assertEqual(work.viewport_mode, "scroll")
            self.assertEqual(event.after, '{"viewport_mode": "scroll"}')

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

    def test_ux_reports_what_users_hit_since_the_last_check(self) -> None:
        events.log_event("http_error", method="POST", path="/api/import-game", status=422, browser="wechat")
        events.log_event("health_fail", work_id=7, detail="script failed to load", browser="wechat")
        events.log_event("http_error", method="GET", path="/favicon.ico", status=404, browser="mobile")
        with self.session() as session:
            user = session.scalar(select(User))
            details = ingest.validate_details(
                title="Broken", category="c", emoji="🔥", art="art-one", description=None
            )
            ingest.capture_failure(
                session, owner=user, details=details, raw_zip=pack_zip([("game.js", b"x")]),
                error="游戏需要包含 index.html",
            )

        report = self.run_ops("ux")

        self.assertIn("never checked before", report)
        self.assertIn("POST /api/import-game → 422", report)
        self.assertIn("work 7: script failed to load", report)
        self.assertIn("wechat 1", report)
        self.assertIn("in-app only", report)
        self.assertIn("unresolved failed uploads: 1", report)
        self.assertIn("other: 1 failure", report)
        self.assertNotIn("favicon", report)

    def test_ux_records_the_run_and_every_skips_until_it_is_due(self) -> None:
        self.run_ops("ux")
        self.assertTrue((self.root / "ux-last-run").is_file())

        skipped = self.run_ops("ux", "--every", "60")
        self.assertIn("next check due in", skipped)
        self.assertNotIn("creation", skipped)

        again = self.run_ops("ux")
        self.assertIn("last check", again)
        self.assertIn("creation: nothing", again)

    def test_ux_since_and_no_mark(self) -> None:
        self.run_ops("ux", "--since", "2h", "--no-mark")
        self.assertFalse((self.root / "ux-last-run").exists())

    def test_refresh_reporter_republishes_games_installed_without_it(self) -> None:
        legacy = config.GAMES_DIR / "af359667cf6a8038"
        legacy.mkdir(parents=True)
        (legacy / "index.html").write_text("<html><head></head></html>")
        with self.session() as session:
            session.add(Work(
                title="Coffee", author="MOOD CAFÉ", category="relax", emoji="☕", art="art-one",
                collection="feed", artifact_hash="af359667cf6a8038",
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

    def test_refresh_reporter_does_not_reactivate_hidden_games(self) -> None:
        legacy = config.GAMES_DIR / "hidden-artifact"
        legacy.mkdir(parents=True)
        (legacy / "index.html").write_text("<html><head></head></html>")
        with self.session() as session:
            session.add(Work(
                title="Hidden", author="A", category="c", emoji="🎮", art="art-one",
                collection="feed", artifact_hash="hidden-artifact", status="hidden",
            ))
            session.commit()

        self.run_ops("refresh-reporter")
        with self.session() as session:
            self.assertEqual(session.scalar(select(Work.status)), "hidden")


if __name__ == "__main__":
    unittest.main()
