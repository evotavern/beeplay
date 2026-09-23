import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app import ux


def http(path: str, status: int, browser: str, method: str = "POST") -> dict:
    return {"event": "http_error", "method": method, "path": path, "status": status, "browser": browser}


class SummarizeTests(unittest.TestCase):
    def test_groups_failures_by_area_signature_and_browser(self) -> None:
        summary = ux.summarize([
            http("/api/import-game", 422, "wechat"),
            http("/api/import-game", 422, "wechat"),
            http("/api/import-game", 422, "desktop"),
            {"event": "client_error", "kind": "upload", "message": "网络断开了 (no response)", "browser": "wechat"},
            {"event": "health_fail", "work_id": 16, "detail": "script failed to load: /games/x/app.js", "browser": "wechat"},
            http("/favicon.ico", 404, "mobile", method="GET"),
            {"event": "created", "work_id": 3},
        ])

        creation = summary["creation"]
        self.assertEqual([(g.signature, g.count) for g in creation], [
            ("POST /api/import-game → 422", 3),
            ("upload: 网络断开了 (no response)", 1),
        ])
        self.assertEqual(dict(creation[0].browsers), {"wechat": 2, "desktop": 1})
        self.assertFalse(creation[0].in_app_only)
        self.assertTrue(creation[1].in_app_only)

        [crash] = summary["gameplay"]
        self.assertEqual(crash.signature, "work 16: script failed to load: /games/x/app.js")
        self.assertEqual([g.signature for g in summary["other"]], ["GET /favicon.ico → 404"])

    def test_ids_in_paths_are_folded_into_one_group(self) -> None:
        summary = ux.summarize([
            http("/api/works/15/like", 401, "wechat"),
            http("/api/works/16/like", 401, "wechat"),
        ])
        [group] = summary["other"]
        self.assertEqual((group.signature, group.count), ("POST /api/works/{id}/like → 401", 2))

    def test_page_errors_on_the_create_view_count_as_creation(self) -> None:
        summary = ux.summarize([
            {"event": "client_error", "kind": "error", "message": "x is undefined", "page": "/create", "browser": "qq"},
            {"event": "client_error", "kind": "error", "message": "y is undefined", "page": "/", "browser": "qq"},
        ])
        self.assertEqual([g.signature for g in summary["creation"]], ["error: x is undefined"])
        self.assertEqual([g.signature for g in summary["other"]], ["error: y is undefined"])

    def test_counts_a_failed_play_once_and_not_the_derived_auto_hide(self) -> None:
        summary = ux.summarize([
            {"event": "health_fail", "work_id": 16, "artifact": "a", "session": "play-1",
             "kind": "error", "detail": "boom", "browser": "wechat"},
            {"event": "health_fail", "work_id": 16, "artifact": "a", "session": "play-1",
             "kind": "timeout", "detail": "no load", "browser": "wechat"},
            {"event": "auto_hidden", "work_id": 16, "failed": 3, "plays": 3},
        ])

        self.assertEqual([(group.signature, group.count) for group in summary["gameplay"]], [
            ("work 16: boom", 1),
        ])


class ReadEventsTests(unittest.TestCase):
    def test_keeps_only_events_inside_the_window_and_skips_broken_lines(self) -> None:
        now = datetime(2026, 9, 23, 12, 0)
        lines = [
            {"event": "http_error", "at": "2026-09-23T10:00:00Z"},
            {"event": "http_error", "at": "2026-09-23T11:30:00Z"},
        ]
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "events.jsonl"
            log.write_text("\n".join(json.dumps(line) for line in lines) + "\nnot json\n")
            with patch.object(Path, "read_text", side_effect=AssertionError("loads whole log")):
                events = ux.read_events(log, since=now - timedelta(hours=1))
            self.assertEqual([e["at"] for e in events], ["2026-09-23T11:30:00Z"])
            self.assertEqual(ux.read_events(Path(directory) / "missing.jsonl", since=now), [])


class DurationTests(unittest.TestCase):
    def test_parses_minutes_hours_and_days(self) -> None:
        self.assertEqual(ux.parse_duration("30m"), timedelta(minutes=30))
        self.assertEqual(ux.parse_duration("2h"), timedelta(hours=2))
        self.assertEqual(ux.parse_duration("1d"), timedelta(days=1))
        with self.assertRaises(ValueError):
            ux.parse_duration("soon")


if __name__ == "__main__":
    unittest.main()
