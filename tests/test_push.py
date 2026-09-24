"""deploy/push.py: what the briefing stops on, warns about and shows."""

import datetime
import importlib.util
import os
import pty
import select
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("push", ROOT / "deploy" / "push.py")
push = importlib.util.module_from_spec(spec)
sys.modules["push"] = push  # dataclasses look their module up there
spec.loader.exec_module(push)

LIVE = "a" * 40
STATUS = {"live": LIVE, "live_known_by": "version.json", "pr": 6, "released_at": "2026-09-24T14:49:35+08:00",
          "previous": "b" * 40, "lock": None, "last": {"action": "release", "pr": 6}, "database": "0009",
          "since_release": {"client_error": 0, "server_error": 0, "health_fail": 0, "play_ok": 22},
          "github": True}


def pr(**changes) -> "push.Candidate":
    fields = dict(kind="pr", pr=8, title="fix: taps respond", commit="c" * 40, url="https://github.com/x/pull/8",
                  author="vxtto", files=["assets/js/app.js", "app/templates/base.html"], additions=40,
                  deletions=10, commits=2)
    fields.update(changes)
    return push.Candidate(**fields)


def facts(candidate=None, **changes) -> "push.Facts":
    fields = dict(candidate=candidate or pr(), status=dict(STATUS), live_in_main=True, behind_main=0,
                  ci_exists=False, others=[], work=[], summary=["Taps respond at once."],
                  tests=["点赞，看按钮立刻变红"])
    fields.update(changes)
    return push.Facts(**fields)


class StopTests(unittest.TestCase):
    def stops(self, f):
        return push.assess(f)[0]

    def test_a_green_up_to_date_pr_has_no_stops(self):
        self.assertEqual(self.stops(facts()), [])

    def test_a_pr_behind_main_stops(self):
        self.assertIn("PR #8 is 3 commit(s) behind main: merge main into it first",
                      self.stops(facts(behind_main=3)))

    def test_a_stacked_pr_stops(self):
        self.assertIn("PR #8 is based on fix/asset-cache-epoch, not main: merge that first",
                      self.stops(facts(pr(base="fix/asset-cache-epoch"))))

    def test_taking_back_live_code_stops(self):
        # The 13:39 release: main did not contain the live #6.
        stops = self.stops(facts(live_in_main=False))
        self.assertTrue(any(s.startswith(f"main does not contain the live {LIVE[:7]}") for s in stops), stops)

    def test_not_knowing_what_is_live_stops(self):
        status = dict(STATUS, live=None, live_known_by="unknown: no commit on main matches the live files")
        self.assertIn("cannot tell what is live (unknown: no commit on main matches the live files)",
                      self.stops(facts(status=status)))

    def test_a_first_install_with_nothing_live_does_not_stop(self):
        status = dict(STATUS, live=None, live_known_by="nothing live yet (first install)")
        self.assertEqual(self.stops(facts(status=status)), [])

    def test_a_release_already_running_stops(self):
        status = dict(STATUS, lock="release abc123 since 15:02:11 (pid 42)")
        self.assertIn("another release is running: release abc123 since 15:02:11 (pid 42)",
                      self.stops(facts(status=status)))

    def test_failed_or_running_tests_stop(self):
        failing = pr(checks=[{"name": "unit", "status": "COMPLETED", "conclusion": "FAILURE"}])
        self.assertIn("tests failed: unit", self.stops(facts(failing, ci_exists=True)))
        running = pr(checks=[{"name": "e2e", "status": "IN_PROGRESS", "conclusion": ""}])
        self.assertIn("tests still running: e2e", self.stops(facts(running, ci_exists=True)))

    def test_tests_that_never_ran_stop_once_ci_exists(self):
        self.assertIn("the tests have not run on this PR", self.stops(facts(ci_exists=True)))
        self.assertNotIn("the tests have not run on this PR", self.stops(facts(ci_exists=False)))

    def test_closed_draft_and_conflicting_prs_stop(self):
        stops = self.stops(facts(pr(state="MERGED", draft=True, mergeable="CONFLICTING")))
        self.assertTrue(any("merged, not open" in s for s in stops))
        self.assertIn("PR #8 is a draft", stops)
        self.assertIn("PR #8 conflicts with main", stops)

    def test_a_server_that_cannot_read_github_stops(self):
        self.assertIn("the server cannot read the repository on GitHub (it has to be public)",
                      self.stops(facts(status=dict(STATUS, github=False))))


class WarningTests(unittest.TestCase):
    def warnings(self, f):
        return push.assess(f)[1]

    def test_no_ci_is_a_warning_until_ci_exists(self):
        self.assertIn("no CI yet: nothing has run the tests", self.warnings(facts()))

    def test_another_pr_editing_the_same_files_is_a_warning(self):
        other = {"number": 2, "title": "FE-0923", "author": {"login": "Double-935"},
                 "files": [{"path": "app/templates/base.html"}]}
        self.assertIn("PR #2 FE-0923 (Double-935) also edits app/templates/base.html",
                      self.warnings(facts(others=[other])))

    def test_unpushed_work_on_this_laptop_is_a_warning(self):
        work = [{"name": "github-repo-audit", "dirty": True, "unpushed": 2, "session": True}]
        self.assertIn("worktree github-repo-audit: 2 unpushed commit(s), uncommitted changes, "
                      "a session is running there", self.warnings(facts(work=work)))

    def test_migrations_dependencies_and_server_changes_are_warnings(self):
        candidate = pr(files=["migrations/versions/0010_x.py", "uv.lock", "deploy/beeplay.caddy"])
        warnings = self.warnings(facts(candidate))
        self.assertIn("changes the database: 0010_x.py", warnings)
        self.assertIn("changes dependencies", warnings)
        self.assertIn("changes the server setup: beeplay.caddy", warnings)

    def test_errors_in_prod_since_the_last_release_are_a_warning(self):
        status = dict(STATUS, since_release={"client_error": 5, "server_error": 1, "play_ok": 3})
        self.assertIn("prod since the last release: 5 page errors, 1 server errors",
                      self.warnings(facts(status=status)))

    def test_a_rollback_not_yet_reverted_is_a_warning(self):
        status = dict(STATUS, last={"action": "rollback", "pr": 6})
        self.assertIn("the last release (PR #6) was rolled back: main still has it unless its revert "
                      "PR was merged", self.warnings(facts(status=status)))


class OutputTests(unittest.TestCase):
    def test_the_briefing_fits_on_one_screen_and_says_what_matters(self):
        f = facts()
        text = push.render(f, *push.assess(f))
        self.assertLessEqual(len(text.splitlines()), 24)
        self.assertIn("SHIPPING  PR #8 fix: taps respond (vxtto)", text)
        self.assertIn(f"LIVE NOW  {LIVE[:7]} · PR #6 · since 2026-09-24 14:49 · database 0009", text)
        self.assertIn("new file URLs: app.js", text)
        self.assertIn("IN SHORT  Taps respond at once.", text)
        self.assertIn("TO TEST   • 点赞，看按钮立刻变红", text)
        self.assertIn("STOPS     none", text)
        self.assertIn("PROD      since the last release: 22 plays ok, 0 page errors, 0 server errors", text)

    def test_before_any_stamped_release_the_briefing_says_so(self):
        status = dict(STATUS, released_at=None, live_known_by="matched by its files", pr=None)
        text = push.render(facts(status=status), [], [])
        self.assertIn(f"LIVE NOW  {LIVE[:7]} · matched by its files · database 0009", text)
        self.assertIn("PROD      no release on record yet: counts start with this one", text)

    def test_the_lark_post_is_chinese_and_names_the_tester(self):
        post = push.lark_post(pr(), ["点赞，看按钮立刻变红", "滑到下一个游戏"],
                              datetime.datetime(2026, 9, 24, 15, 4))
        self.assertEqual(post.splitlines(), [
            "🚀 BeePlay 已更新（15:04）：PR #8 fix: taps respond",
            "@李佳蓓 请在手机上测试：",
            "• 点赞，看按钮立刻变红",
            "• 滑到下一个游戏",
            "https://beeplay.top",
            "https://github.com/x/pull/8",
        ])

    def test_without_claude_the_summary_falls_back_to_the_title(self):
        path = os.environ["PATH"]
        os.environ["PATH"] = "/nonexistent"
        try:
            summary, tests = push.summarize(pr(), "diff")
        finally:
            os.environ["PATH"] = path
        self.assertEqual(summary, ["fix: taps respond  (no summary: claude is not installed here)"])
        self.assertEqual(tests, ["打开 beeplay.top，看看「fix: taps respond」是否正常"])

    def test_answers_come_from_the_terminal_not_a_pipe(self):
        for answer, piped in [("ship", "cancel"), ("cancel", "ship")]:
            with self.subTest(answer=answer):
                master, slave = pty.openpty()
                code = (
                    "import os, runpy, sys\n"
                    # Opening a terminal as a session leader acquires it.
                    "terminal = os.open(sys.argv[1], os.O_RDWR)\n"
                    "push = runpy.run_path(sys.argv[2])\n"
                    "print(repr(push['ask']('确认 ship: ')))\n"
                )
                try:
                    with subprocess.Popen(
                        [sys.executable, "-c", code, os.ttyname(slave), str(ROOT / "deploy" / "push.py")],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                        text=True, start_new_session=True,
                    ) as child:
                        try:
                            child.stdin.write(piped + "\n")
                            child.stdin.flush()
                            self.assertTrue(select.select([master], [], [], 5)[0], "no terminal prompt")
                            self.assertIn("确认 ship: ", os.read(master, 4096).decode())
                            os.write(master, (answer + "\n").encode())
                            out, err = child.communicate(timeout=5)
                            self.assertEqual(child.returncode, 0, err)
                            self.assertEqual(out.strip(), repr(answer))
                        finally:
                            if child.poll() is None:
                                child.kill()
                                child.communicate()
                finally:
                    os.close(master)
                    os.close(slave)

    def test_without_a_terminal_piped_ship_is_refused(self):
        child = subprocess.run(
            [sys.executable, "-c",
             "import runpy, sys; runpy.run_path(sys.argv[1])['ask']('ship: ')",
             str(ROOT / "deploy" / "push.py")],
            input="ship\n", capture_output=True, text=True, start_new_session=True, timeout=5,
        )
        self.assertNotEqual(child.returncode, 0)
        self.assertIn("the ship prompt needs a terminal", child.stderr)


if __name__ == "__main__":
    unittest.main()
