"""deploy/beeplay-release: finding the live commit from the files alone, and
what it reads from the server's logs."""

import importlib.machinery
import importlib.util
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("beeplay_release", str(ROOT / "deploy" / "beeplay-release"))
spec = importlib.util.spec_from_loader("beeplay_release", loader)
release = importlib.util.module_from_spec(spec)
loader.exec_module(release)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
                          env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}).stdout.strip()


class WhatsLiveTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.repo = Path(work.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        (self.repo / "app").mkdir()
        (self.repo / "app" / "main.py").write_text("print('v1')\n")
        (self.repo / "AGENTS.md").write_text("notes\n")
        (self.repo / "CLAUDE.md").symlink_to("AGENTS.md")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", "v1")
        self.v1 = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "app" / "main.py").write_text("print('v2')\n")
        git(self.repo, "commit", "-qam", "v2")
        self.v2 = git(self.repo, "rev-parse", "HEAD")
        self.live = Path(work.name) / "srv"
        self.live.mkdir()

    def deploy(self, commit: str) -> None:
        """What release.sh leaves in /srv/beeplay, plus what runs add there."""
        archive = subprocess.run(["git", "-C", str(self.repo), "archive", commit], capture_output=True, check=True)
        subprocess.run(["tar", "-x", "-C", str(self.live)], input=archive.stdout, check=True)
        (self.live / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
        (self.live / ".venv" / "bin" / "python").write_text("")
        (self.live / "app" / "__pycache__").mkdir(exist_ok=True)
        (self.live / "app" / "__pycache__" / "main.cpython-314.pyc").write_bytes(b"\0")
        (self.live / "version.json").write_text("{}")

    def test_the_commit_whose_files_are_live_is_found(self):
        self.deploy(self.v1)
        self.assertEqual(release.whats_live(self.live, [self.v2, self.v1], self.repo), self.v1)

    def test_a_changed_or_extra_file_matches_nothing(self):
        self.deploy(self.v2)
        (self.live / "app" / "main.py").write_text("print('edited on the server')\n")
        self.assertIsNone(release.whats_live(self.live, [self.v2, self.v1], self.repo))
        (self.live / "app" / "main.py").write_text("print('v2')\n")
        (self.live / "app" / "stray.py").write_text("")
        self.assertIsNone(release.whats_live(self.live, [self.v2, self.v1], self.repo))

    def test_a_symlink_compares_as_its_target(self):
        self.deploy(self.v2)
        self.assertEqual(release.tree_files(self.live)["CLAUDE.md"], release.blob_id(b"AGENTS.md"))
        self.assertEqual(release.whats_live(self.live, [self.v2], self.repo), self.v2)

    def test_blob_ids_are_git_s(self):
        blob = git(self.repo, "rev-parse", f"{self.v2}:app/main.py")
        self.assertEqual(release.blob_id(b"print('v2')\n"), blob)


class ServerStateTests(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.dir = Path(work.name)

    def test_the_database_version_is_read_without_writing(self):
        db = self.dir / "beeplay.db"
        with sqlite3.connect(db) as connection:
            connection.execute("create table alembic_version (version_num text)")
            connection.execute("insert into alembic_version values ('0009')")
        self.assertEqual(release.db_version(db), "0009")
        self.assertEqual(release.db_version(self.dir / "missing.db"), "none")

    def test_errors_since_the_release_leave_out_scanners_and_shown_messages(self):
        events = self.dir / "events.jsonl"
        lines = [
            {"event": "client_error", "kind": "script", "at": "2026-09-24T06:50:00Z"},
            {"event": "client_error", "kind": "shown", "at": "2026-09-24T06:51:00Z"},
            {"event": "http_error", "status": 502, "at": "2026-09-24T06:52:00Z"},
            {"event": "http_error", "status": 404, "at": "2026-09-24T06:52:30Z"},
            {"event": "play_ok", "at": "2026-09-24T06:53:00Z"},
            {"event": "client_error", "kind": "error", "at": "2026-09-24T06:40:00Z"},  # before
        ]
        events.write_text("".join(json.dumps(line) + "\n" for line in lines) + "not json\n")
        self.assertEqual(release.errors_since("2026-09-24T14:49:35+08:00", events),
                         {"client_error": 1, "server_error": 1, "health_fail": 0, "play_ok": 1})

    def test_the_release_log_round_trips(self):
        log = self.dir / "logs" / "releases.jsonl"
        release.record({"action": "release", "commit": "abc", "pr": 8}, log)
        release.record({"action": "rollback", "pr": 8}, log)
        self.assertEqual([e["action"] for e in release.history(log)], ["release", "rollback"])


if __name__ == "__main__":
    unittest.main()
