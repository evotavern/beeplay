"""Accounts end to end: silent sign-up, handles, passwords, merging, photos."""

import io
from datetime import timedelta
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import accounts, config, identity, main
from app.models import User, UserSession, Work, WorkLike, WorkSave, utcnow
import test_http

SEED = "af359667cf6a8038"


def photo_bytes(size=(640, 480), fmt="JPEG", exif_gps=True) -> bytes:
    image = Image.new("RGB", size, (200, 120, 40))
    output = io.BytesIO()
    if exif_gps and fmt == "JPEG":
        exif = Image.Exif()
        exif[0x8825] = {2: (45.0, 30.0, 0.0), 1: "N"}  # GPS IFD
        exif[0x0112] = 6  # rotated: the file is stored sideways
        image.save(output, fmt, exif=exif)
    else:
        image.save(output, fmt)
    return output.getvalue()


class AccountTests(test_http.HttpTestCase):
    def setUp(self) -> None:
        super().setUp()
        accounts.handle_failures._failures.clear()
        accounts.ip_failures._failures.clear()
        with Session(self.engine) as session:
            self.seed_id = session.scalar(select(Work.id).where(Work.artifact_hash == SEED))

    def other_client(self) -> TestClient:
        return TestClient(main.app, base_url="http://testserver")

    def like(self, client=None, active=True):
        return (client or self.client).post(f"/api/works/{self.seed_id}/like", json={"active": active})

    def set_password(self, password="honey123", client=None, **extra):
        return (client or self.client).post(
            "/api/account/password", json={"password": password, **extra}
        )

    def login(self, handle, password="honey123", client=None, **headers):
        return (client or self.client).post(
            "/api/login", json={"handle": handle, "password": password}, headers=headers
        )

    # --- silent accounts --------------------------------------------------

    def test_browsing_never_makes_an_account(self) -> None:
        for path in ("/", "/discover", "/create", "/messages", "/u/beeplay", "/login"):
            self.client.get(path)
        self.assertIsNone(self.client.cookies.get(accounts.COOKIE_NAME))
        with Session(self.engine) as session:
            self.assertEqual(session.scalars(select(User.slug)).all(), ["beeplay"])

    def test_an_automatic_account_has_a_name_handle_and_colour(self) -> None:
        user = self.sign_up()
        self.assertRegex(user.slug, r"^bee\d{6}$")
        self.assertRegex(user.name, r"^小蜜蜂 #\d{4}$")
        self.assertFalse(user.handle_locked)
        self.assertIsNone(user.password_hash)
        page = self.client.get("/profile").text
        self.assertIn(user.name, page)
        self.assertIn("设置密码，换设备也能登录", page)
        self.assertNotIn("data-account-logout", page)

    def test_the_cookie_is_a_token_whose_hash_alone_is_stored(self) -> None:
        self.sign_up()
        token = self.client.cookies.get(accounts.COOKIE_NAME)
        with Session(self.engine) as session:
            [stored] = session.scalars(select(UserSession.token_hash)).all()
        self.assertEqual(stored, accounts.token_hash(token))
        self.assertNotEqual(stored, token)

    def test_plain_http_never_issues_a_session(self) -> None:
        with patch.object(identity, "ALLOW_INSECURE_COOKIES", False):
            self.assertEqual(self.like().status_code, 403)
            self.assertEqual(self.client.get("/profile").status_code, 403)
        self.assertIsNone(self.client.cookies.get(accounts.COOKIE_NAME))

    # --- profile ------------------------------------------------------------

    def test_profile_edits_are_checked_and_show_on_cards_by_the_current_name(self) -> None:
        self.sign_up()
        self.assertEqual(self.upload().status_code, 200)
        change = {"name": "  蜜 蜂  ", "bio": "做小游戏", "avatar_fill": "ffe08a"}
        saved = self.client.post("/api/account/profile", json=change)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["name"], "蜜 蜂")
        for bad in ({"name": " "}, {"name": "x" * 21}, {"avatar_fill": "000000"}, {"bio": "x" * 121}):
            with self.subTest(bad=bad):
                self.assertEqual(self.client.post("/api/account/profile", json={**change, **bad}).status_code, 422)
        # Cards show who the author is now, not the name they published under.
        self.assertIn("蜜 蜂", self.client.get("/").text)
        self.assertIn("蜜 蜂", self.client.get("/discover").text)

    def test_profile_writes_from_another_site_are_refused(self) -> None:
        self.sign_up()
        change = {"name": "Mallory", "bio": "", "avatar_fill": "ffe08a"}
        for headers in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                refused = self.client.post("/api/account/profile", json=change, headers=headers)
                self.assertEqual(refused.status_code, 403)

    def test_the_public_page_shows_only_live_games(self) -> None:
        user = self.sign_up()
        live = self.upload(title="Live One").json()["artifact"]
        self.upload(title="Hidden One")
        with Session(self.engine) as session:
            hidden = session.scalar(select(Work).where(Work.title == "Hidden One"))
            hidden.status = "hidden"
            session.commit()
        stranger = self.other_client()
        page = stranger.get(f"/u/{user.slug}").text
        self.assertIn("Live One", page)
        self.assertNotIn("Hidden One", page)
        self.assertNotIn("这是你", page)
        self.assertIn("这是你", self.client.get(f"/u/{user.slug}").text)
        self.assertIn(f'href="/u/{user.slug}"', stranger.get("/").text)
        self.assertEqual(stranger.get("/u/nobody_here").status_code, 404)
        self.assertTrue(live)

    # --- photos ---------------------------------------------------------------

    def test_a_photo_is_squared_small_webp_without_exif(self) -> None:
        self.sign_up()
        reply = self.client.post(
            "/api/account/photo", files={"photo": ("me.jpg", photo_bytes(), "image/jpeg")}
        )
        self.assertEqual(reply.status_code, 200, reply.text)
        url = reply.json()["avatar"]
        self.assertRegex(url, r"^/avatars/[0-9a-f]{16}\.webp$")
        # /avatars is mounted on the real directory at import; read the file.
        stored_file = config.AVATARS_DIR / url.removeprefix("/avatars/")
        with Image.open(stored_file) as stored:
            self.assertEqual((stored.format, stored.size), ("WEBP", (256, 256)))
            self.assertNotIn(0x8825, stored.getexif())
            self.assertNotIn("exif", stored.info)
        self.assertIn(url, self.client.get("/profile").text)

        removed = self.client.delete("/api/account/photo")
        self.assertTrue(removed.json()["avatar"].startswith("data:image/svg+xml"))

    def test_bad_photos_are_refused_with_a_reason(self) -> None:
        self.sign_up()
        for name, raw in (("notes.txt", b"hello"), ("huge.jpg", b"\xff" * (5 * 1024 * 1024 + 1))):
            with self.subTest(name=name):
                reply = self.client.post("/api/account/photo", files={"photo": (name, raw, "image/jpeg")})
                self.assertEqual(reply.status_code, 422)
                self.assertIsInstance(reply.json()["detail"], str)

    # --- passwords and handles --------------------------------------------------

    def test_the_first_password_picks_and_locks_the_handle(self) -> None:
        self.sign_up()
        for handle, reason in (("ab", "3–20"), ("Has Space", "3–20"), ("admin", "保留"), ("beeplay", "保留")):
            with self.subTest(handle=handle):
                refused = self.set_password(handle=handle)
                self.assertEqual(refused.status_code, 422)
                self.assertIn(reason, refused.json()["detail"])
        self.assertEqual(self.set_password(password="12345", handle="honey_lab").status_code, 422)

        chosen = self.set_password(handle="@Honey_Lab")
        self.assertEqual(chosen.status_code, 200, chosen.text)
        self.assertEqual(chosen.json()["handle"], "honey_lab")
        # Locked: a later change keeps the handle whatever is sent.
        again = self.set_password(password="honey456", handle="other_name", current_password="honey123")
        self.assertEqual(again.json()["handle"], "honey_lab")
        self.assertIn("data-account-logout", self.client.get("/profile").text)

    def test_a_handle_already_taken_is_refused(self) -> None:
        other = self.other_client()
        self.sign_up(other)
        self.assertEqual(self.set_password(handle="taken_one", client=other).status_code, 200)
        self.sign_up()
        refused = self.set_password(handle="taken_one")
        self.assertEqual(refused.status_code, 422)
        self.assertIn("有人用了", refused.json()["detail"])

    def test_changing_the_password_needs_the_old_one_and_signs_out_other_devices(self) -> None:
        self.sign_up()
        self.set_password(handle="honey_lab")
        phone = self.other_client()
        self.assertEqual(self.login("honey_lab", client=phone).status_code, 200)

        self.assertEqual(self.set_password(password="new-pass", current_password="wrong").status_code, 422)
        self.assertEqual(self.set_password(password="new-pass", current_password="honey123").status_code, 200)
        self.assertIsNone(self.current(phone))
        self.assertIsNotNone(self.current())
        self.assertEqual(self.login("honey_lab", client=phone).status_code, 422)
        self.assertEqual(self.login("honey_lab", "new-pass", client=phone).status_code, 200)

    # --- login, merge, logout ----------------------------------------------------

    def test_logging_in_folds_this_devices_automatic_account_in(self) -> None:
        # The real account, with a like and a save.
        owner = self.sign_up()
        self.set_password(handle="honey_lab")
        self.like()
        self.client.post(f"/api/works/{self.seed_id}/save", json={"active": True})

        # The same person in WeChat's browser: an automatic account that liked
        # the same game and uploaded one of its own.
        wechat = self.other_client()
        self.assertEqual(self.like(wechat).status_code, 200)
        self.assertEqual(self.upload_with(wechat, title="From WeChat").status_code, 200)
        throwaway = self.current(wechat)
        self.assertIn("会合并到你登录的账号", wechat.get("/login").text)

        reply = self.login("HONEY_LAB", client=wechat)
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertTrue(reply.json()["merged"])
        self.assertEqual(self.current(wechat).id, owner.id)
        with Session(self.engine) as session:
            self.assertIsNone(session.get(User, throwaway.id))
            self.assertEqual(session.query(WorkLike).count(), 1)
            self.assertEqual(session.query(WorkSave).count(), 1)
            moved = session.scalar(select(Work).where(Work.title == "From WeChat"))
            self.assertEqual(moved.user_id, owner.id)
        self.assertIn("From WeChat", wechat.get("/profile").text)
        self.assertIn("From WeChat", self.client.get("/profile").text)

    def test_logging_in_from_another_real_account_switches_without_merging(self) -> None:
        self.sign_up()
        self.set_password(handle="first_one")
        self.like()
        other = self.other_client()
        self.sign_up(other)
        self.set_password(handle="second_one", client=other)

        reply = self.login("second_one")
        self.assertFalse(reply.json()["merged"])
        with Session(self.engine) as session:
            first = session.scalar(select(User).where(User.slug == "first_one"))
            self.assertEqual(session.query(WorkLike).filter_by(user_id=first.id).count(), 1)
        self.assertEqual(self.current().slug, "second_one")

    def test_wrong_passwords_are_vague_and_limited(self) -> None:
        self.sign_up()
        self.set_password(handle="honey_lab")
        stranger = self.other_client()
        self.assertEqual(self.login("honey_lab", "nope", client=stranger).json()["detail"], "用户名或密码不对")
        self.assertEqual(self.login("no_such_bee", "nope", client=stranger).json()["detail"], "用户名或密码不对")
        for _ in range(9):
            self.login("honey_lab", "nope", client=stranger)
        blocked = self.login("honey_lab", client=stranger)
        self.assertEqual(blocked.status_code, 422)
        self.assertIn("15 分钟", blocked.json()["detail"])

    def test_a_login_from_another_site_is_refused(self) -> None:
        self.sign_up()
        self.set_password(handle="honey_lab")
        stranger = self.other_client()
        self.assertEqual(self.login("honey_lab", client=stranger, Origin="https://evil.example").status_code, 403)

    def test_logout_needs_a_password_and_ends_only_this_device(self) -> None:
        self.sign_up()
        self.assertEqual(self.client.post("/api/logout").status_code, 409)
        self.set_password(handle="honey_lab")
        phone = self.other_client()
        self.login("honey_lab", client=phone)

        self.assertEqual(self.client.post("/api/logout").status_code, 200)
        self.assertIsNone(self.current())
        self.assertIsNotNone(self.current(phone))

    # --- staff reset ---------------------------------------------------------------

    def test_a_reset_link_works_once_and_signs_everyone_out(self) -> None:
        self.sign_up()
        self.set_password(handle="honey_lab")
        with Session(self.engine) as session:
            token = accounts.issue_reset(session, "honey_lab")

        lost_phone = self.other_client()
        self.assertIn("@honey_lab", lost_phone.get("/reset", params={"token": token}).text)
        reply = lost_phone.post("/api/reset", json={"token": token, "password": "fresh-pass"})
        self.assertEqual(reply.status_code, 200, reply.text)
        self.assertEqual(self.current(lost_phone).slug, "honey_lab")
        self.assertIsNone(self.current())

        self.assertIn("链接已失效", lost_phone.get("/reset", params={"token": token}).text)
        self.assertEqual(lost_phone.post("/api/reset", json={"token": token, "password": "again-pass"}).status_code, 422)
        self.assertEqual(self.login("honey_lab", "fresh-pass").status_code, 200)

    def test_a_reset_link_expires(self) -> None:
        self.sign_up()
        self.set_password(handle="honey_lab")
        with Session(self.engine) as session:
            token = accounts.issue_reset(session, "honey_lab")
            later = utcnow() + accounts.RESET_TTL + timedelta(seconds=1)
            self.assertIsNone(accounts.reset_target(session, token, now=later))

    def upload_with(self, client, **overrides):
        form = {"title": "Block Drop", "category": "brainrot", "emoji": "🧱", "art": "art-two"}
        form.update(overrides)
        return client.post(
            "/api/import-game", data=form,
            files={"bundle": ("game.zip", test_http.game_zip(), "application/zip")},
        )

    def upload(self, **overrides):
        return self.upload_with(self.client, **overrides)


class LimiterTests(test_http.unittest.TestCase):
    def test_only_failures_count_and_they_age_out(self) -> None:
        limiter = accounts.FailureLimiter(limit=2, window_s=10)
        self.assertFalse(limiter.blocked("k", now=0))
        limiter.fail("k", now=0)
        limiter.fail("k", now=1)
        self.assertTrue(limiter.blocked("k", now=2))
        self.assertFalse(limiter.blocked("other", now=2))
        self.assertFalse(limiter.blocked("k", now=11))


if __name__ == "__main__":
    test_http.unittest.main()
