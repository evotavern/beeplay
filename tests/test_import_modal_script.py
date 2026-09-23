import unittest
from pathlib import Path


class ImportModalScriptTests(unittest.TestCase):
    def test_successful_import_reenables_the_persistent_submit_button(self) -> None:
        script = (Path(__file__).parents[1] / "assets" / "js" / "app.js").read_text()

        self.assertIn("var importSubmit = importGameForm.querySelector", script)
        self.assertIn("importSubmit.disabled = true;", script)
        self.assertIn(".finally(function () { importSubmit.disabled = false; });", script)
        self.assertIn("importGameForm.reset();\n    importSubmit.disabled = false;", script)
        self.assertIn("服务器拒绝了上传，请检查文件大小后重试", script)

    def test_upload_reports_progress_while_the_bundle_is_in_flight(self) -> None:
        # fetch() cannot observe upload progress; a multi-MB bundle on a slow
        # link otherwise sits behind a spinner with no feedback at all.
        root = Path(__file__).parents[1]
        script = (root / "assets" / "js" / "app.js").read_text()
        shell = (root / "app" / "templates" / "base.html").read_text()

        self.assertIn("xhr.upload.onprogress", script)
        self.assertNotIn('fetch("/api/import-game"', script)
        self.assertIn('id="importProgress"', shell)
