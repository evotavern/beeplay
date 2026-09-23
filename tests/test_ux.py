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
    def test_groups_failures_by_area_and_person(self) -> None:
        summary = ux.summarize([
            http("/api/import-game", 422, "wechat", person="p-a", at=at(1)),
            http("/api/import-game", 422, "wechat", person="p-a", at=at(2)),
            http("/api/import-game", 422, "desktop", person="p-b", at=at(3)),
            {"event": "client_error", "kind": "upload", "message": "网络断开了 (no response)",
             "browser": "wechat", "person": "p-a", "at": at(4)},
            {"event": "health_fail", "work_id": 16, "detail": "script failed to load: /games/x/app.js",
             "browser": "wechat", "person": "p-a", "at": at(5)},
            http("/favicon.ico", 404, "mobile", method="GET", person="p-c", at=at(6)),
            {"event": "created", "work_id": 3},
        ])

        [first, second] = summary.areas["creation"]
        self.assertEqual((first.key, first.total), ("p-a", 3))
        self.assertEqual(dict(first.failures), {
            "POST /api/import-game → 422": 2, "upload: 网络断开了 (no response)": 1,
        })
        self.assertTrue(first.in_app_only)
        self.assertEqual((second.key, second.total, second.in_app_only), ("p-b", 1, False))

        [crash] = summary.areas["gameplay"]
        self.assertEqual(list(crash.failures), ["work 16: script failed to load: /games/x/app.js"])
        [favicon] = summary.areas["other"]
        self.assertEqual(list(favicon.failures), ["GET /favicon.ico → 404"])

    def test_ids_in_paths_are_folded_into_one_signature(self) -> None:
        summary = ux.summarize([
            http("/api/works/15/like", 401, "wechat", person="p-a"),
            http("/api/works/16/like", 401, "wechat", person="p-a"),
        ])
        [person] = summary.areas["other"]
        self.assertEqual(dict(person.failures), {"POST /api/works/{id}/like → 401": 2})

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
        [person] = summary.areas["gameplay"]
        self.assertEqual(dict(person.failures), {"work 16: boom": 1})

    def test_scanner_404s_without_a_cookie_are_noise_but_a_players_are_listed(self) -> None:
        summary = ux.summarize([
            {**http("/.env", 404, "desktop", method="GET"), "cookie": False},
            {**http("/wp-login.php", 405, "desktop"), "cookie": False},
            {"event": "http_error", "method": "GET", "path": "/old.php", "status": 404, "browser": "desktop"},
            http("/favicon.ico", 404, "mobile", method="GET", person="p-player"),
            {**http("/api/works/1/like", 500, "desktop"), "cookie": False},
        ])
        self.assertEqual(summary.noise, 3)
        self.assertEqual(
            sorted(sig for person in summary.areas["other"] for sig in person.failures),
            ["GET /favicon.ico → 404", "POST /api/works/{id}/like → 500"],
        )

    def test_outcome_says_whether_the_person_got_through(self) -> None:
        summary = ux.summarize([
            http("/api/import-game", 401, "desktop", person="p-stuck", at=at(1)),
            http("/api/import-game", 401, "desktop", person="p-stuck", at=at(2)),
            http("/api/import-game", 422, "desktop", person="p-back", at=at(3)),
            {"event": "creation_ok", "person": "p-back", "at": at(4)},
            {"event": "creation_ok", "person": "p-early", "at": at(1)},
            http("/api/import-game", 422, "desktop", person="p-early", at=at(5)),
            {"event": "play_ok", "person": "p-stuck", "at": at(9)},
        ])
        outcomes = [(person.key, person.outcome) for person in summary.areas["creation"]]
        self.assertEqual(outcomes, [
            ("p-stuck", ux.STUCK), ("p-early", ux.OPEN), ("p-back", ux.RECOVERED),
        ])

    def test_what_the_player_saw_comes_from_the_page_or_is_inferred(self) -> None:
        summary = ux.summarize([
            http("/api/import-game", 401, "desktop", person="p-a", who="bee-2"),
            {"event": "client_error", "kind": "shown", "area": "creation", "person": "p-a",
             "message": "先认领一个身份，再上传游戏吧", "next": "redirected", "lost": True, "status": 401},
            http("/api/import-game", 401, "desktop", person="p-b"),
            {"event": "health_fail", "work_id": 7, "kind": "timeout", "detail": "no load signal",
             "session": "s", "person": "p-c"},
        ])
        [with_report, without] = summary.areas["creation"]
        self.assertEqual(with_report.who, {"bee-2"})
        self.assertEqual(list(with_report.saw), [
            '"先认领一个身份，再上传游戏吧", sent to another page, input lost',
        ])
        self.assertIn("chosen files and details lost", without.inferred["POST /api/import-game → 401"])
        [timeout] = summary.areas["gameplay"]
        self.assertIn("stays as it was", timeout.inferred["work 7: no load signal"])

    def test_events_from_before_person_ids_group_by_browser_string(self) -> None:
        summary = ux.summarize([
            http("/api/import-game", 422, "desktop", ua="Mac Chrome"),
            http("/api/import-game", 422, "desktop", ua="Mac Chrome"),
            http("/api/import-game", 422, "desktop", ua="Windows Edge"),
        ])
        self.assertEqual(sorted(person.total for person in summary.areas["creation"]), [1, 2])
        # No success events existed yet either, so "stuck" would be a guess.
        self.assertEqual({person.outcome for person in summary.areas["creation"]}, {ux.UNKNOWN})


class RenderTests(unittest.TestCase):
    def test_lists_every_person_with_outcome_saw_line_and_hidden_noise(self) -> None:
        summary = ux.summarize([
            http("/api/import-game", 401, "desktop", person="p-a", who="bee-2", at=at(1)),
            http("/api/import-game", 401, "desktop", person="p-a", who="bee-2", at=at(2)),
            http("/profile", 500, "wechat", method="GET", person="p-b", at=at(3)),
            {**http("/.env", 404, "desktop", method="GET"), "cookie": False},
        ])
        text = ux.render(
            summary, since=datetime(2026, 9, 23, 7, 0), now=datetime(2026, 9, 23, 8, 0),
            window="last 1h", unresolved_uploads=0,
        )
        self.assertIn("creation: 1 person (1 stuck) · 2 failures", text)
        self.assertIn("STUCK · bee-2 · desktop · p-a", text)
        self.assertIn("  2×  POST /api/import-game → 401", text)
        self.assertIn("saw (inferred): sent to /claim", text)
        self.assertIn("gameplay: nothing", text)
        self.assertIn("other: 1 person (1 no success since) · 1 failure", text)
        self.assertIn("wechat · in-app only · p-b", text)
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
