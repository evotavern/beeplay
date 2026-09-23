import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app import config, events
from app.models import Base, User, Work, WorkEvent


class LogEventTests(unittest.TestCase):
    def test_appends_one_json_line_per_event(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "logs" / "events.jsonl"
            with patch.object(config, "EVENTS_LOG", log_path):
                events.log_event("upload_ok", work_id=3, slug="bee-2")
                events.log_event("upload_failed", slug="bee-2", error="游戏需要包含 index.html")

            lines = [json.loads(line) for line in log_path.read_text().splitlines()]
        self.assertEqual([line["event"] for line in lines], ["upload_ok", "upload_failed"])
        self.assertEqual(lines[0]["work_id"], 3)
        self.assertEqual(lines[1]["error"], "游戏需要包含 index.html")
        self.assertIn("at", lines[0])


class RecordTests(unittest.TestCase):
    def test_records_an_audit_row_and_a_log_line(self) -> None:
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        with Session(engine) as session, tempfile.TemporaryDirectory() as directory:
            owner = User(
                slug="bee-2", name="小蜜蜂", handle="@b", bio="", avatar_fill="fff",
                level=1, xp=0, xp_goal=1, position=0,
            )
            session.add(owner)
            session.flush()
            work = Work(
                title="G", author="小蜜蜂", category="meme", emoji="🎮", art="art-one",
                collection="feed", artifact_hash="abc", user_id=owner.id,
            )
            session.add(work)
            session.flush()
            log_path = Path(directory) / "events.jsonl"
            with patch.object(config, "EVENTS_LOG", log_path):
                events.record(
                    session, work, actor="ops:vitto", kind="status_changed",
                    before={"status": "live"}, after={"status": "hidden"},
                )
                session.commit()
            line = json.loads(log_path.read_text())

            row = session.scalar(select(WorkEvent))
            self.assertEqual((row.actor, row.kind), ("ops:vitto", "status_changed"))
            self.assertEqual(json.loads(row.after), {"status": "hidden"})
            self.assertEqual(line["work_id"], work.id)
        self.assertEqual(line["event"], "status_changed")
        self.assertEqual((line["slug"], line["artifact"]), ("bee-2", "abc"))
        engine.dispose()


class AlertTests(unittest.TestCase):
    def test_does_nothing_without_a_webhook(self) -> None:
        with patch.object(config, "ALERT_WEBHOOK", ""), patch.object(events, "_post") as post:
            events.alert("hello")
        post.assert_not_called()

    def test_posts_a_feishu_text_message_when_configured(self) -> None:
        with patch.object(config, "ALERT_WEBHOOK", "https://example.invalid/hook"), \
                patch.object(events, "_post") as post:
            events.alert("hello", wait=True)
        url, payload = post.call_args.args
        self.assertEqual(url, "https://example.invalid/hook")
        self.assertEqual(payload, {"msg_type": "text", "content": {"text": "hello"}})


if __name__ == "__main__":
    unittest.main()
