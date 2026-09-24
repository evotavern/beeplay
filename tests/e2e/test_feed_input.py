"""Taps, swipes and trackpad input on the feed, in Chromium and WebKit.

How to run it: see harness.py. The symptoms came from a MacBook (Chrome) and
two iPhones (Safari, WeChat); "iphone" emulates the phones' viewport and touch.
"""

import unittest

import harness
from harness import LIME, active_game, tap

server = browsers = None


def setUpModule() -> None:
    global server, browsers
    browsers = harness.Browsers()
    server = harness.Server().start()


def tearDownModule() -> None:
    if browsers:
        browsers.close()
    if server:
        server.stop()


def engines():
    return list(browsers.browsers)


def hold(page, path: str) -> list:
    """Keep requests to `path` waiting until the test lets them go."""
    held = []
    page.route(lambda url: url.split("?")[0].endswith(path), lambda route: held.append(route))
    return held


class NavTests(unittest.TestCase):
    def nav(self, page, target: str):
        return page.locator(f".bottom-nav .nav-item[data-view-target='{target}']")

    def test_the_tapped_item_shows_as_current_not_hovered(self) -> None:
        # iOS keeps :hover on whatever was tapped last, and .nav-item:hover
        # outranked .nav-item.active: the current page's icon showed white.
        for engine in engines():
            with self.subTest(engine=engine), browsers.page(engine, "iphone", server.url + "/") as page:
                tap(page, "iphone", self.nav(page, "discover"))
                page.wait_for_selector("#viewport .view[data-view='discover']")
                page.wait_for_timeout(300)
                color = self.nav(page, "discover").evaluate("e => getComputedStyle(e).color")
                self.assertEqual(color, LIME)

    def test_the_highlight_moves_on_the_tap_not_when_the_page_arrives(self) -> None:
        for engine in engines():
            with self.subTest(engine=engine), browsers.page(engine, "iphone", server.url + "/") as page:
                held = hold(page, "/discover")
                tap(page, "iphone", self.nav(page, "discover"))
                page.wait_for_timeout(150)
                self.assertTrue(held, "the nav tap sent no request")
                active = page.eval_on_selector_all(
                    ".bottom-nav .nav-item.active", "items => items.map(i => i.dataset.viewTarget)")
                self.assertEqual(active, ["discover"])
                held[0].continue_()
                page.wait_for_selector("#viewport .view[data-view='discover']")

    def test_the_highlight_goes_back_when_the_page_fails_to_load(self) -> None:
        for engine in engines():
            with self.subTest(engine=engine), browsers.page(engine, "iphone", server.url + "/") as page:
                page.route(lambda url: url.split("?")[0].endswith("/discover"),
                           lambda route: route.fulfill(status=502, body="bad gateway"))
                tap(page, "iphone", self.nav(page, "discover"))
                page.wait_for_timeout(500)
                active = page.eval_on_selector_all(
                    ".bottom-nav .nav-item.active", "items => items.map(i => i.dataset.viewTarget)")
                self.assertEqual(active, ["home"])


class TrayLayoutTests(unittest.TestCase):
    def test_the_bottom_nav_never_covers_the_action_row(self) -> None:
        # Measured per card against the card's own bottom edge, which is the
        # screen's bottom edge whenever that card is showing.
        for engine in engines():
            with browsers.page(engine, "iphone", server.url + "/") as page:
                for width, height in [(375, 667), (390, 844), (430, 932)]:
                    for inset in (0, 34):
                        with self.subTest(engine=engine, size=f"{width}x{height}", inset=inset):
                            page.set_viewport_size({"width": width, "height": height})
                            page.evaluate("px => document.documentElement.style.setProperty('--safe-bottom', px)",
                                          f"{inset}px")
                            page.wait_for_timeout(150)
                            gaps = page.evaluate("""() => {
                              const nav = document.querySelector('.bottom-nav').getBoundingClientRect();
                              const navTop = innerHeight - nav.top;
                              return [...document.querySelectorAll('.game-card')].map(card => {
                                const c = card.getBoundingClientRect();
                                const a = card.querySelector('.game-tray-actions').getBoundingClientRect();
                                return Math.round(c.bottom - a.bottom - navTop);
                              });
                            }""")
                            self.assertTrue(all(gap >= 4 for gap in gaps), f"action row to nav gaps: {gaps}")


class TraySwipeTests(unittest.TestCase):
    def test_a_mouse_drag_that_ends_over_the_game_still_switches(self) -> None:
        # Released over the game's frame, the pointerup went to the game and
        # the drag was never seen to end.
        for engine in engines():
            with self.subTest(engine=engine), browsers.page(engine, "macbook", server.url + "/") as page:
                tray = page.locator(".game-card.active-game .game-tray").bounding_box()
                x, y = tray["x"] + tray["width"] / 2, tray["y"] + 30
                page.mouse.move(x, y)
                page.mouse.down()
                for step in range(1, 11):
                    page.mouse.move(x, y - 15 * step)
                page.mouse.up()
                page.wait_for_timeout(600)
                self.assertEqual(active_game(page), 1)

    def test_a_touch_swipe_up_the_tray_switches(self) -> None:
        if "chromium" not in engines():
            self.skipTest("real touch sequences need Chromium's CDP")
        with browsers.page("chromium", "iphone", server.url + "/") as page:
            tray = page.locator(".game-card.active-game .game-tray").bounding_box()
            x, y = tray["x"] + tray["width"] / 2, tray["y"] + 30
            cdp = page.context.new_cdp_session(page)
            cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
            for step in range(1, 9):
                cdp.send("Input.dispatchTouchEvent",
                         {"type": "touchMove", "touchPoints": [{"x": x, "y": y - 15 * step}]})
            cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
            page.wait_for_timeout(600)
            self.assertEqual(active_game(page), 1)

    def test_a_drag_starting_on_a_button_does_not_press_it(self) -> None:
        for engine in engines():
            with self.subTest(engine=engine), browsers.page(engine, "macbook", server.url + "/") as page:
                like = page.locator(".game-card.active-game [data-game-action='like']")
                box = like.bounding_box()
                x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
                page.mouse.move(x, y)
                page.mouse.down()
                for step in range(1, 11):
                    page.mouse.move(x, y - 15 * step)
                for step in range(9, -1, -1):
                    page.mouse.move(x, y - 15 * step)
                page.mouse.up()
                page.wait_for_timeout(400)
                self.assertEqual(page.locator("[data-game-action='like'].active").count(), 0)


class TrackpadTests(unittest.TestCase):
    def flick(self, page) -> None:
        # A macOS two-finger flick: wheel events every frame, decaying for
        # over a second after the fingers lift.
        for i in range(60):
            page.mouse.wheel(0, max(1, 80 * 0.93 ** i))
            page.wait_for_timeout(20)

    def over_tray(self, page) -> None:
        tray = page.locator(".game-card.active-game .game-tray").bounding_box()
        page.mouse.move(tray["x"] + tray["width"] / 2, tray["y"] + 30)

    def test_one_flick_moves_one_game(self) -> None:
        for engine in engines():
            with self.subTest(engine=engine), browsers.page(engine, "macbook", server.url + "/") as page:
                self.over_tray(page)
                self.flick(page)
                page.wait_for_timeout(600)
                self.assertEqual(active_game(page), 1)

    def test_two_flicks_move_two_games(self) -> None:
        for engine in engines():
            with self.subTest(engine=engine), browsers.page(engine, "macbook", server.url + "/") as page:
                self.over_tray(page)
                self.flick(page)
                page.wait_for_timeout(500)
                self.over_tray(page)
                self.flick(page)
                page.wait_for_timeout(600)
                self.assertEqual(active_game(page), 2)


class ToggleTests(unittest.TestCase):
    def test_like_shows_on_the_tap_and_stays_once_saved(self) -> None:
        for engine in engines():
            with self.subTest(engine=engine), browsers.page(engine, "iphone", server.url + "/") as page:
                held = hold(page, "/like")
                like = page.locator(".game-card.active-game [data-game-action='like']")
                count = like.locator("[data-social-count='likes']")
                before = int(count.text_content())
                tap(page, "iphone", like)
                page.wait_for_timeout(150)
                self.assertTrue(held, "the like sent no request")
                self.assertTrue(like.evaluate("e => e.classList.contains('active')"))
                self.assertEqual(int(count.text_content()), before + 1)
                held[0].continue_()
                page.wait_for_timeout(400)
                self.assertTrue(like.evaluate("e => e.classList.contains('active')"))

    def test_a_refused_like_goes_back(self) -> None:
        for engine in engines():
            with self.subTest(engine=engine), browsers.page(engine, "iphone", server.url + "/") as page:
                page.route(lambda url: url.endswith("/like"), lambda route: route.fulfill(
                    status=500, content_type="application/json", body='{"detail": "操作没有保存，请重试"}'))
                like = page.locator(".game-card.active-game [data-game-action='like']")
                before = like.locator("[data-social-count='likes']").text_content()
                tap(page, "iphone", like)
                page.wait_for_timeout(400)
                self.assertFalse(like.evaluate("e => e.classList.contains('active')"))
                self.assertEqual(like.locator("[data-social-count='likes']").text_content(), before)
                self.assertIn("操作没有保存", page.locator("#toast").text_content())

    def test_follow_shows_on_the_tap(self) -> None:
        for engine in engines():
            with self.subTest(engine=engine), browsers.page(engine, "iphone", server.url + "/") as page:
                held = hold(page, "/follow")
                follow = page.locator(".game-card.active-game [data-follow-user]")
                tap(page, "iphone", follow)
                page.wait_for_timeout(150)
                self.assertTrue(held, "the follow sent no request")
                self.assertEqual(follow.text_content(), "已关注")
                held[0].continue_()
                page.wait_for_timeout(400)
                self.assertEqual(follow.text_content(), "已关注")


if __name__ == "__main__":
    unittest.main()
