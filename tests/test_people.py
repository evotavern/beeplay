import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import config, people


class PersonIdTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.log = Path(self.directory.name) / "logs" / "events.jsonl"
        self.patch = patch.object(config, "EVENTS_LOG", self.log)
        self.patch.start()

    def tearDown(self) -> None:
        self.patch.stop()
        self.directory.cleanup()

    def test_same_player_same_day_only(self) -> None:
        today = people.person_id("203.0.113.9", "Chrome", day="2026-09-23")
        self.assertEqual(today, people.person_id("203.0.113.9", "Chrome", day="2026-09-23"))
        self.assertNotEqual(today, people.person_id("203.0.113.9", "Chrome", day="2026-09-24"))
        self.assertNotEqual(today, people.person_id("203.0.113.9", "Safari", day="2026-09-23"))
        self.assertNotEqual(today, people.person_id("203.0.113.10", "Chrome", day="2026-09-23"))
        self.assertNotIn("203", today)

    def test_the_key_is_private_to_the_server_and_survives_a_restart(self) -> None:
        first = people.person_id("203.0.113.9", "Chrome", day="2026-09-23")
        key = self.log.with_name("person-key")
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
        people._keys.clear()
        self.assertEqual(first, people.person_id("203.0.113.9", "Chrome", day="2026-09-23"))


if __name__ == "__main__":
    unittest.main()
