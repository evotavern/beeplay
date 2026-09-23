import unittest
from pathlib import Path

ROOT = Path(__file__).parents[1]
REPORTER = (ROOT / "assets" / "js" / "page-reporter.js").read_text()
SCRIPT = (ROOT / "assets" / "js" / "app.js").read_text()
SHELL = (ROOT / "app" / "templates" / "base.html").read_text()


class PageReporterTests(unittest.TestCase):
    def test_loads_before_every_other_script_so_it_sees_them_fail(self) -> None:
        reporter = SHELL.index("asset('js/page-reporter.js')")
        self.assertLess(reporter, SHELL.index("asset('vendor/htmx.min.js')"))
        self.assertLess(reporter, SHELL.index("asset('js/app.js')"))

    def test_reports_exceptions_rejections_and_scripts_that_fail_to_load(self) -> None:
        self.assertIn('"/api/client-error"', REPORTER)
        self.assertIn('window.addEventListener("error"', REPORTER)
        self.assertIn("}, true);", REPORTER)  # capture phase: resource errors do not bubble
        self.assertIn('window.addEventListener("unhandledrejection"', REPORTER)
        self.assertIn('report("script"', REPORTER)

    def test_a_broken_page_cannot_flood_the_log(self) -> None:
        self.assertIn("if (sent >= MAX_REPORTS) return;", REPORTER)

    def test_upload_failures_the_server_never_saw_are_reported(self) -> None:
        # Refusals the app answered with JSON are already logged server-side as
        # http_error; only network drops and proxy refusals (e.g. 413) are not.
        self.assertIn("answered = true;", SCRIPT)
        self.assertIn('if (!answered) reportUploadFailure(error, httpStatus);', SCRIPT)
        self.assertIn('window.beeplayReport("upload"', SCRIPT)

    def test_every_upload_failure_reports_what_the_player_was_shown(self) -> None:
        shown = SCRIPT.index('window.beeplayReport("shown", error.message')
        self.assertLess(SCRIPT.index('textContent = error.message;'), shown)
        # Nothing sends the uploader away any more: the form stays filled in.
        self.assertIn('next: "stayed"', SCRIPT)
        self.assertIn("lost: false", SCRIPT)

    def test_generation_errors_report_the_message_they_put_on_screen(self) -> None:
        generation = (ROOT / "assets" / "js" / "generation.js").read_text()
        self.assertIn('window.beeplayReport("shown", text, { area: "creation"', generation)
        self.assertIn("if (error) reportShown(text);", generation)
        self.assertEqual(generation.count("previewProblem("), 5)


if __name__ == "__main__":
    unittest.main()
