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
