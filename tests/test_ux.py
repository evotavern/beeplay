import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app import ux


def http(path: str, status: int, browser: str, method: str = "POST", **extra) -> dict:
    return {"event": "http_error", "method": method, "path": path, "status": status,
            "browser": browser, "cookie": True, **extra}


def at(minute: int) -> str:
    return f"2026-09-23T07:{minute:02d}:00Z"


class SummarizeTests(unittest.TestCase):
    def test_groups_failures_by_area_and_browser_string(self) -> None:
        summary = ux.summarize([
            http("/api/import-game", 422, "wechat", ua="WeChat A", at=at(1)),
            http("/api/import-game", 422, "wechat", ua="WeChat A", at=at(2)),
            http("/api/import-game", 422, "desktop", ua="Mac Chrome", at=at(3)),
            {"event": "client_error", "kind": "upload", "message": "网络断开了 (no response)",
             "browser": "wechat", "ua": "WeChat A", "at": at(4)},
            {"event": "health_fail", "work_id": 16, "detail": "script failed to load: /games/x/app.js",
             "browser": "wechat", "ua": "WeChat A", "at": at(5)},
            http("/favicon.ico", 404, "mobile", method="GET", ua="Android", at=at(6)),
            {"event": "created", "work_id": 3},
        ])

        [first, second] = summary.areas["creation"]
        self.assertEqual(first.total, 3)
        self.assertEqual(dict(first.failures), {
            "POST /api/import-game → 422": 2, "upload: 网络断开了 (no response)": 1,
        })
        self.assertTrue(first.in_app_only)
        self.assertEqual((second.total, second.in_app_only), (1, False))
        self.assertNotEqual(first.key, second.key)

        [crash] = summary.areas["gameplay"]
        self.assertEqual(list(crash.failures), ["work 16: script failed to load: /games/x/app.js"])
        [favicon] = summary.areas["other"]
        self.assertEqual(list(favicon.failures), ["GET /favicon.ico → 404"])

    def test_ids_in_paths_are_folded_into_one_signature(self) -> None:
        summary = ux.summarize([
            http("/api/works/15/like", 401, "wechat"),
            http("/api/works/16/like", 401, "wechat"),
        ])
        [source] = summary.areas["other"]
        self.assertEqual(dict(source.failures), {"POST /api/works/{id}/like → 401": 2})

    def test_page_errors_count_toward_the_area_of_their_page(self) -> None:
        summary = ux.summarize([
            {"event": "client_error", "kind": "error", "message": "x is undefined", "page": "/create", "browser": "qq"},
            {"event": "client_error", "kind": "error", "message": "y is undefined", "page": "/", "browser": "qq"},
            {"event": "client_error", "kind": "error", "message": "z is undefined", "page": "/profile", "browser": "qq"},
        ])
        self.assertEqual(list(summary.areas["creation"][0].failures), ["error: x is undefined"])
        self.assertEqual(list(summary.areas["gameplay"][0].failures), ["error: y is undefined"])
        self.assertEqual(list(summary.areas["other"][0].failures), ["error: z is undefined"])

    def test_generation_requests_are_creation(self) -> None:
        summary = ux.summarize([http("/api/generations/current", 401, "desktop", method="GET")])
        self.assertEqual(len(summary.areas["creation"]), 1)

    def test_counts_a_failed_play_once_and_not_the_derived_auto_hide(self) -> None:
        summary = ux.summarize([
            {"event": "health_fail", "work_id": 16, "artifact": "a", "session": "play-1",
             "kind": "error", "detail": "boom", "browser": "wechat"},
            {"event": "health_fail", "work_id": 16, "artifact": "a", "session": "play-1",
             "kind": "timeout", "detail": "no load", "browser": "wechat"},
            {"event": "auto_hidden", "work_id": 16, "failed": 3, "plays": 3},
        ])
        [source] = summary.areas["gameplay"]
        self.assertEqual(dict(source.failures), {"work 16: boom": 1})

    def test_404s_without_a_cookie_are_noise_but_a_players_are_listed(self) -> None:
        summary = ux.summarize([
            {**http("/.env", 404, "desktop", method="GET"), "cookie": False},
            {**http("/wp-login.php", 405, "desktop"), "cookie": False},
            # Not saying whether there was a cookie counts as a scanner.
            {"event": "http_error", "method": "GET", "path": "/old.php", "status": 404, "browser": "desktop"},
            http("/favicon.ico", 404, "mobile", method="GET"),
            {**http("/api/works/1/like", 500, "desktop"), "cookie": False},
        ])
        self.assertEqual(summary.noise, 3)
        self.assertEqual(
            sorted(sig for source in summary.areas["other"] for sig in source.failures),
            ["GET /favicon.ico → 404", "POST /api/works/{id}/like → 500"],
        )

    def test_what_the_player_saw_is_inferred_from_the_failure(self) -> None:
        summary = ux.summarize([
            http("/api/import-game", 401, "desktop"),
            {"event": "health_fail", "work_id": 7, "kind": "timeout", "detail": "no load signal",
             "session": "s"},
        ])
        [upload] = summary.areas["creation"]
        self.assertIn("chosen files and details lost", upload.inferred["POST /api/import-game → 401"])
        [timeout] = summary.areas["gameplay"]
        self.assertIn("stays as it was", timeout.inferred["work 7: no load signal"])


class RenderTests(unittest.TestCase):
    def test_lists_every_source_with_its_saw_line_and_hidden_noise(self) -> None:
        summary = ux.summarize([
            http("/api/import-game", 401, "desktop", ua="Mac Chrome", at=at(1)),
            http("/api/import-game", 401, "desktop", ua="Mac Chrome", at=at(2)),
            http("/profile", 500, "wechat", method="GET", ua="WeChat", at=at(3)),
            {**http("/.env", 404, "desktop", method="GET"), "cookie": False},
        ])
        text = ux.render(
            summary, since=datetime(2026, 9, 23, 7, 0), now=datetime(2026, 9, 23, 8, 0),
            window="last 1h", unresolved_uploads=0,
        )
        self.assertIn("creation: 2 failures from 1 browser string", text)
        self.assertRegex(text, r"desktop · ua-[0-9a-f]{6} \(one browser string\)")
        self.assertIn("  2×  POST /api/import-game → 401", text)
        self.assertEqual(text.count("saw (inferred): sent to /claim"), 1)
        self.assertIn("gameplay: nothing", text)
        self.assertIn("other: 1 failure from 1 browser string", text)
        self.assertIn("wechat · in-app only · ua-", text)
        self.assertIn("noise hidden: 1", text)


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
