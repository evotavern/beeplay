import hashlib
import re
import unittest

from app import config, main


class AssetUrlTests(unittest.TestCase):
    def test_url_carries_a_hash_of_the_current_contents(self) -> None:
        # Caddy caches /assets/ for a week, so a release must change the URL,
        # or returning visitors keep running last week's app.js.
        contents = (config.BASE_DIR / "assets" / "js" / "app.js").read_bytes()
        expected = hashlib.sha256(contents).hexdigest()[:12]
        self.assertEqual(main.asset("js/app.js"), f"/assets/js/app.js?v={expected}")

    def test_every_script_and_image_in_the_shell_is_versioned(self) -> None:
        shell = (config.BASE_DIR / "app" / "templates" / "base.html").read_text()
        bare = re.findall(r'(?:src|href)="/?assets/[^"{]*"', shell)
        self.assertEqual(bare, [])


if __name__ == "__main__":
    unittest.main()
