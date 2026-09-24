import hashlib
import re
import unittest

from app import config, main

# What the shell linked to on 2026-09-24 while Caddy answered /assets/ with 403
# and a week's max-age. Browsers keep serving that 403 for these exact URLs.
POISONED = {
    "js/app.js": "e7fde950dc6d",
    "vendor/htmx.min.js": "e209dda5c823",
    "js/page-reporter.js": "69fb74a5eab0",
    "js/generation.js": "d01f49f8accf",
    "js/account.js": "2983f6e5d04b",
    "css/generation.css": "b62f9f57f748",
    "css/account.css": "02a9db7fe702",
    "icons/beeplay-logo.png": "5534d0762431",
}


class AssetUrlTests(unittest.TestCase):
    def test_url_carries_a_hash_of_the_epoch_and_the_current_contents(self) -> None:
        # Caddy caches /assets/ for a week, so a release must change the URL,
        # or returning visitors keep running last week's app.js.
        contents = (config.BASE_DIR / "assets" / "js" / "app.js").read_bytes()
        expected = hashlib.sha256(main.ASSET_EPOCH + contents).hexdigest()[:12]
        self.assertEqual(main.asset("js/app.js"), f"/assets/js/app.js?v={expected}")

    def test_no_url_that_answered_403_in_the_outage_is_linked_again(self) -> None:
        for path, digest in POISONED.items():
            with self.subTest(path=path):
                self.assertNotEqual(main.asset(path), f"/assets/{path}?v={digest}")

    def test_every_script_and_image_in_the_shell_is_versioned(self) -> None:
        shell = (config.BASE_DIR / "app" / "templates" / "base.html").read_text()
        bare = re.findall(r'(?:src|href)="/?assets/[^"{]*"', shell)
        self.assertEqual(bare, [])


if __name__ == "__main__":
    unittest.main()
