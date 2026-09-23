import unittest
from pathlib import Path


SCRIPT = (Path(__file__).parents[1] / "assets" / "js" / "app.js").read_text()


class SocialScriptTests(unittest.TestCase):
    def test_a_new_mount_records_one_view_and_resume_does_not(self) -> None:
        self.assertEqual(SCRIPT.count('socialFetch(play.workId, "view"'), 1)
        self.assertLess(
            SCRIPT.index("if (session && session.hash === hash)"),
            SCRIPT.index("watchHealth(session)"),
        )

    def test_share_is_recorded_only_after_a_real_share_or_copy(self) -> None:
        native = SCRIPT.index("await navigator.share")
        copied = SCRIPT.index("completed = await copyShareUrl")
        recorded = SCRIPT.index('socialFetch(card.dataset.gameId, "share"')
        self.assertLess(native, recorded)
        self.assertLess(copied, recorded)

    def test_a_completed_share_is_confirmed_before_it_is_counted(self) -> None:
        confirmed = SCRIPT.index('showToast(navigator.share ? "已分享 "')
        recorded = SCRIPT.index('socialFetch(card.dataset.gameId, "share"')
        self.assertLess(confirmed, recorded)

    def test_completion_contract_remains_deliberately_deferred(self) -> None:
        self.assertIn("TODO(completion-contract)", SCRIPT)
        self.assertIn("ten real games", SCRIPT)


if __name__ == "__main__":
    unittest.main()
