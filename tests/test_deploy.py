"""Deployment configuration contracts."""

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CaddyConfigTests(unittest.TestCase):
    def setUp(self) -> None:
        self.config = (ROOT / "deploy" / "beeplay.caddy").read_text()

    def test_canonical_site_serves_static_files_and_proxies_the_app(self) -> None:
        self.assertIn("beeplay.top {", self.config)
        self.assertIn("handle_path /assets/*", self.config)
        self.assertIn("root * /srv/beeplay/assets", self.config)
        self.assertIn('Cache-Control "public, max-age=604800"', self.config)
        self.assertIn("handle_path /games/*", self.config)
        self.assertIn("root * /var/lib/beeplay/games", self.config)
        self.assertIn('Cache-Control "public, max-age=31536000, immutable"', self.config)
        self.assertIn('header Content-Security-Policy "sandbox allow-scripts"', self.config)
        # Sandboxed games fetch their own files from Origin: null.
        self.assertIn('header Access-Control-Allow-Origin "*"', self.config)
        self.assertIn("reverse_proxy 127.0.0.1:8000", self.config)

    def test_redirects_preserve_the_requested_uri(self) -> None:
        self.assertIn("www.beeplay.top {", self.config)
        self.assertIn("redir https://beeplay.top{uri} permanent", self.config)
        self.assertIn("http://47.251.140.176 {", self.config)

    def test_unknown_http_hosts_are_rejected(self) -> None:
        self.assertIn("http:// {", self.config)
        self.assertIn("abort", self.config)

    def test_safe_headers_are_enabled_without_hsts(self) -> None:
        self.assertIn('X-Content-Type-Options "nosniff"', self.config)
        self.assertIn('Referrer-Policy "strict-origin-when-cross-origin"', self.config)
        self.assertNotIn("Strict-Transport-Security", self.config)

    def test_long_caching_is_only_for_successful_responses(self) -> None:
        # A 403 cached for a week kept phones broken after the 2026-09-24 fix.
        blocks = self.config.split("header Cache-Control")[1:]
        self.assertEqual(len(blocks), 3)  # /assets/, /games/, /avatars/
        for block in blocks:
            self.assertIn("match status 2xx 304", block[: block.index("}")])


class DeploymentScriptTests(unittest.TestCase):
    def test_production_environment_defaults_to_secure_canonical_url(self) -> None:
        environment = (ROOT / "deploy" / "beeplay.env").read_text()
        self.assertIn("BEEPLAY_PUBLIC_URL=https://beeplay.top", environment)
        self.assertNotIn("BEEPLAY_ALLOW_INSECURE_CLAIMS", environment)

    def test_one_time_setup_splits_shared_caddy_and_retires_nginx(self) -> None:
        setup = (ROOT / "deploy" / "setup-caddy.sh").read_text()
        self.assertIn("MOONANSWER=$SITES_DIR/moonanswer.caddy", setup)
        self.assertIn("import /etc/caddy/sites/*.caddy", setup)
        self.assertIn("caddy validate --config", setup)
        self.assertIn(". /etc/caddy/cloudflare.env", setup)
        self.assertIn("systemctl disable --now nginx", setup)
        self.assertIn("systemctl enable --now caddy", setup)
        self.assertIn("trap restore_config EXIT", setup)
        self.assertIn('cp -a "$BACKUP_DIR/beeplay.env" "$ENV_FILE"', setup)
        self.assertIn("systemctl disable --now caddy || true", setup)
        self.assertIn('systemctl enable --now nginx || true', setup)
        self.assertIn("BEEPLAY_PUBLIC_URL=https://beeplay.top", setup)
        self.assertIn("BEEPLAY_ALLOW_INSECURE_CLAIMS", setup)
        self.assertIn("Manual fallback", setup)

    def test_normal_release_owns_only_the_beeplay_fragment(self) -> None:
        release = (ROOT / "deploy" / "release.sh").read_text()
        self.assertIn("/etc/caddy/sites/beeplay.caddy", release)
        self.assertIn("validate_caddy /etc/caddy/Caddyfile", release)
        self.assertIn(". /etc/caddy/cloudflare.env", release)
        self.assertIn("systemctl reload caddy", release)
        self.assertIn("rm -f /etc/caddy/sites/beeplay.caddy", release)
        self.assertNotIn("/etc/caddy/sites/moonanswer.caddy", release)
        self.assertNotIn("/etc/nginx/sites-available/beeplay", release)
        self.assertNotIn("systemctl reload nginx", release)

    def test_nothing_live_changes_before_the_rehearsal_passes(self) -> None:
        release = (ROOT / "deploy" / "release.sh").read_text()
        rehearsal = release.index("-m app.ops migrate")
        new_site = release.index('validate_caddy "$NEXT/caddy/Caddyfile"')
        dry_run_ends = release.index('echo "dry run passed')
        swap = release.index('sync_tree "$SRC" "$APP"')
        stop = release.index("systemctl stop beeplay\nbeeplay-ops migrate")
        self.assertLess(rehearsal, swap)
        self.assertLess(new_site, swap)
        self.assertLess(dry_run_ends, release.index("SWAPPED=1"))
        self.assertLess(swap, stop)
        # The rehearsal migrates a copy, never the live database.
        self.assertIn("BEEPLAY_DB_PATH=$NEXT/rehearsal.db", release)

    def test_served_files_get_their_modes_on_the_server(self) -> None:
        # A push from a 0700 directory made /srv/beeplay unreadable to Caddy.
        release = (ROOT / "deploy" / "release.sh").read_text()
        self.assertIn("--chmod=Da+rx,Fa+r", release)
        self.assertIn('chmod 755 "$2"', release)

    def test_a_failed_release_goes_back_and_checks_through_caddy(self) -> None:
        release = (ROOT / "deploy" / "release.sh").read_text()
        self.assertIn("trap on_exit EXIT", release)
        self.assertIn('cp -a "$PREV" "$APP"', release)
        # The database only goes back when the version moved, and only when
        # someone types "restore".
        self.assertIn('if [ "$moved" != "$BEFORE" ]', release)
        self.assertIn('[ "$answer" = restore ]', release)
        verify = release[release.index('echo "== verify =="'):]
        self.assertIn("beeplay-check", verify)
        self.assertIn("beeplay-check.timer", release)

    def test_local_deployment_check_covers_scripts_tests_and_caddy(self) -> None:
        check = (ROOT / "deploy" / "test-config.sh").read_text()
        self.assertIn("python -m unittest", check)
        self.assertIn("bash -n", check)
        self.assertIn("caddy validate", check)


if __name__ == "__main__":
    unittest.main()
