import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import config, ingest
from app.game_imports import GameImportError
from app.models import Base, FailedUpload, User, Work, WorkEvent

GAME = [("index.html", b"<head></head><canvas></canvas>")]


def owner(slug: str = "bee-2") -> User:
    return User(
        slug=slug, name="小蜜蜂", handle="@b", bio="", avatar_fill="fff",
        saved_count=0, level=1, xp=0, xp_goal=1, position=0,
    )


class IngestTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.user = owner()
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
        self.details = ingest.validate_details(
            title="Block Drop", category="brainrot", emoji="🧱", art="art-two", description=""
        )

    def tearDown(self) -> None:
        for active in self.patches:
            active.stop()
        self.session.close()
        self.engine.dispose()
        self.directory.cleanup()

    def events(self, work: Work) -> list[str]:
        return list(
            self.session.scalars(
                select(WorkEvent.kind).where(WorkEvent.work_id == work.id).order_by(WorkEvent.id)
            )
        )


class ValidateDetailsTests(unittest.TestCase):
    def test_trims_and_keeps_free_text_categories(self) -> None:
        details = ingest.validate_details(
            title="  Block Drop ", category=" 💀 brainrot ", emoji="🧱", art="art-two", description="  "
        )
        self.assertEqual((details.title, details.category, details.description), ("Block Drop", "💀 brainrot", None))

    def test_requires_title_category_emoji_and_a_known_art(self) -> None:
        good = dict(title="T", category="c", emoji="🎮", art="art-one", description="")
        for field, value in (("title", " "), ("category", ""), ("emoji", ""), ("art", "art-nine")):
            with self.subTest(field=field), self.assertRaises(ingest.DetailsError):
                ingest.validate_details(**{**good, field: value})


class PublishTests(IngestTestCase):
    def test_publishes_live_under_the_owner_with_an_audit_row(self) -> None:
        work = ingest.publish(
            self.session, owner=self.user, details=self.details, entries=GAME, actor="user:bee-2"
        )

        self.assertEqual((work.status, work.user_id, work.author), ("live", self.user.id, "小蜜蜂"))
        self.assertEqual((work.category, work.emoji, work.art), ("brainrot", "🧱", "art-two"))
        self.assertTrue((config.GAMES_DIR / work.artifact_hash / "index.html").is_file())
        self.assertEqual(self.events(work), ["created"])
        ingest.events.alert.assert_called_once()

    def test_operators_can_publish_unlisted_test_games(self) -> None:
        work = ingest.publish(
            self.session, owner=self.user, details=self.details, entries=GAME,
            actor="ops:vitto", status="unlisted",
        )
        self.assertEqual(work.status, "unlisted")

    def test_a_broken_bundle_creates_nothing(self) -> None:
        with self.assertRaises(GameImportError):
            ingest.publish(
                self.session, owner=self.user, details=self.details,
                entries=[("game.js", b"x")], actor="user:bee-2",
            )
        self.assertIsNone(self.session.scalar(select(Work)))


class ReplaceAndStatusTests(IngestTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.work = ingest.publish(
            self.session, owner=self.user, details=self.details, entries=GAME, actor="user:bee-2"
        )

    def test_replacing_points_at_a_new_directory_and_keeps_the_old_one(self) -> None:
        old = self.work.artifact_hash
        ingest.replace(self.session, self.work, entries=GAME, actor="ops:vitto")

        self.assertNotEqual(self.work.artifact_hash, old)
        self.assertTrue((config.GAMES_DIR / old / "index.html").is_file())
        self.assertEqual(self.events(self.work), ["created", "artifact_replaced"])

    def test_replacing_a_hidden_game_brings_it_back(self) -> None:
        ingest.set_status(self.session, self.work, "hidden", actor="system")
        ingest.replace(self.session, self.work, entries=GAME, actor="ops:vitto")

        self.assertEqual(self.work.status, "live")
        self.assertEqual(
            self.events(self.work),
            ["created", "status_changed", "artifact_replaced", "status_changed"],
        )

    def test_status_change_is_audited_with_before_and_after(self) -> None:
        ingest.set_status(self.session, self.work, "unlisted", actor="ops:vitto")
        row = self.session.scalar(select(WorkEvent).where(WorkEvent.kind == "status_changed"))
        self.assertEqual((json.loads(row.before), json.loads(row.after)),
                         ({"status": "live"}, {"status": "unlisted"}))

    def test_rejects_an_unknown_status(self) -> None:
        with self.assertRaises(ValueError):
            ingest.set_status(self.session, self.work, "archived", actor="ops:vitto")


class CaptureFailureTests(IngestTestCase):
    def test_keeps_the_raw_bundle_and_the_details_for_an_operator(self) -> None:
        failed = ingest.capture_failure(
            self.session, owner=self.user, details=self.details,
            raw_zip=b"PK-not-really", error="游戏需要包含 index.html",
        )

        row = self.session.scalar(select(FailedUpload))
        self.assertEqual((row.id, row.user_id, row.title), (failed.id, self.user.id, "Block Drop"))
        self.assertEqual(Path(row.stored_path).read_bytes(), b"PK-not-really")
        self.assertIsNone(row.resolved_work_id)
        ingest.events.alert.assert_called_once()


if __name__ == "__main__":
    unittest.main()
