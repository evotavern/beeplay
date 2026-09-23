import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import config, health, ingest
from app.models import Base, HealthEvent, User, Work, WorkEvent, utcnow


class HealthTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.directory = tempfile.TemporaryDirectory()
        self.patches = [
            patch.object(config, "EVENTS_LOG", Path(self.directory.name) / "events.jsonl"),
            patch.object(config, "CRASH_MIN_FAILURES", 3),
            patch.object(config, "CRASH_RATIO", 0.5),
            patch.object(config, "CRASH_WINDOW_MIN", 30),
            patch.object(config, "ERROR_WINDOW_S", 30),
            patch.object(health.events, "alert"),
        ]
        for active in self.patches:
            active.start()
        user = User(
            slug="bee-2", name="小蜜蜂", avatar_fill="fff",
        )
        self.session.add(user)
        self.session.flush()
        self.work = Work(
            title="G", author="小蜜蜂", category="c", emoji="🎮", art="art-one",
            collection="feed", artifact_hash="current", user_id=user.id,
        )
        self.session.add(self.work)
        self.session.commit()

    def tearDown(self) -> None:
        for active in self.patches:
            active.stop()
        self.session.close()
        self.engine.dispose()
        self.directory.cleanup()

    def play(self, session_id: str, *signals: tuple[str, int], artifact: str = "current") -> None:
        health.report(self.session, artifact_hash=artifact, session_id=session_id, kind="start", elapsed_ms=0)
        for kind, elapsed in signals:
            health.report(
                self.session, artifact_hash=artifact, session_id=session_id,
                kind=kind, elapsed_ms=elapsed, detail="boom",
            )

    def test_three_failing_plays_out_of_four_hide_a_live_game(self) -> None:
        self.play("a", ("timeout", 10_000))
        self.play("b", ("error", 1_000))
        self.play("c", ("loaded", 500))
        self.assertEqual(self.work.status, "live")
        self.play("d", ("loaded", 400), ("error", 2_000))

        self.assertEqual(self.work.status, "hidden")
        kinds = list(self.session.scalars(select(WorkEvent.actor)))
        self.assertEqual(kinds, ["system"])
        health.events.alert.assert_called_once()

    def test_a_minority_of_failures_does_not_hide(self) -> None:
        for name in "abcdefg":
            self.play(name, ("loaded", 300))
        for name in "xyz":
            self.play(name, ("timeout", 10_000))
        self.assertEqual(self.work.status, "live")

    def test_one_session_failing_repeatedly_counts_once(self) -> None:
        self.play("a", ("error", 100), ("error", 200), ("timeout", 10_000))
        self.play("b", ("error", 100))
        self.assertEqual(self.work.status, "live")

    def test_errors_after_the_first_seconds_are_logged_but_do_not_count(self) -> None:
        for name in "abc":
            self.play(name, ("loaded", 300), ("error", 45_000))
        self.assertEqual(self.work.status, "live")
        self.assertEqual(self.session.scalar(select(HealthEvent).where(HealthEvent.elapsed_ms == 45_000)).detail, "boom")

    def test_failures_older_than_the_window_are_forgotten(self) -> None:
        for name in "ab":
            self.play(name, ("timeout", 10_000))
        old = utcnow() - timedelta(minutes=31)
        for row in self.session.scalars(select(HealthEvent)):
            row.at = old
        self.session.commit()
        self.play("c", ("timeout", 10_000))
        self.assertEqual(self.work.status, "live")

    def test_reports_about_a_replaced_artifact_are_ignored(self) -> None:
        for name in "abc":
            self.play(name, ("timeout", 10_000), artifact="old-version")
        self.assertEqual(self.work.status, "live")
        self.assertIsNone(self.session.scalar(select(HealthEvent)))

    def test_unlisted_test_games_are_never_auto_hidden(self) -> None:
        self.work.status = "unlisted"
        self.session.commit()
        for name in "abc":
            self.play(name, ("timeout", 10_000))
        self.assertEqual(self.work.status, "unlisted")

    def test_rejects_unknown_signals(self) -> None:
        with self.assertRaises(ValueError):
            health.report(self.session, artifact_hash="current", session_id="a", kind="exploded")

    def test_summary_counts_plays_and_failures_for_the_current_artifact(self) -> None:
        self.play("a", ("timeout", 10_000))
        self.play("b", ("loaded", 300))
        summary = health.summary(self.session, self.work)
        self.assertEqual((summary.plays, summary.failed), (2, 1))
        self.assertEqual(summary.recent_errors[0].kind, "timeout")


if __name__ == "__main__":
    unittest.main()
