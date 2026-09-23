import unittest

from app import browsers

# Real User-Agents seen in the production access log.
WECHAT_IPHONE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.78(0x18004e2e) NetType/WIFI Language/zh_CN"
)
WECHAT_ANDROID = (
    "Mozilla/5.0 (Linux; Android 16; 24122RKC7C Build/BP2A.250605.031.A3; wv) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Version/4.0 Chrome/150.0.7871.189 Mobile Safari/537.36 XWEB/1500135 "
    "MMWEBSDK/20260502 MicroMessenger/8.0.76.3141(0x28004C54) WeChat/arm64 Weixin NetType/4G"
)
WECHAT_MAC = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/98.0.4758.102 Safari/537.36 NetType/WIFI MicroMessenger/6.8.0(0x16080000) MacWechat/3.7.1"
)
QQ = (
    "Mozilla/5.0 (Linux; Android 14; V2309A) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/109.0.5414.86 MQQBrowser/6.2 TBS/047601 Mobile Safari/537.36 QQ/9.0.60.17365"
)
DOUYIN = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Mobile/15E148 aweme_30.3.0 JsSdk/2.0 NetType/WIFI Channel/App Store"
)
ANDROID_WEBVIEW = (
    "Mozilla/5.0 (Linux; Android 13; SM-S911B; wv) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Version/4.0 Chrome/120.0.6099.230 Mobile Safari/537.36"
)
IPHONE_SAFARI = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.6 Mobile/15E148 Safari/604.1"
)
ANDROID_CHROME = (
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Mobile Safari/537.36"
)
DESKTOP_CHROME = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/144.0.0.0 Safari/537.36"
)


class FamilyTests(unittest.TestCase):
    def test_in_app_browsers(self) -> None:
        self.assertEqual(browsers.family(WECHAT_IPHONE), "wechat")
        self.assertEqual(browsers.family(WECHAT_ANDROID), "wechat")
        self.assertEqual(browsers.family(WECHAT_MAC), "wechat")
        self.assertEqual(browsers.family(QQ), "qq")
        self.assertEqual(browsers.family(DOUYIN), "douyin")
        self.assertEqual(browsers.family(ANDROID_WEBVIEW), "webview")

    def test_regular_browsers(self) -> None:
        self.assertEqual(browsers.family(IPHONE_SAFARI), "mobile")
        self.assertEqual(browsers.family(ANDROID_CHROME), "mobile")
        self.assertEqual(browsers.family(DESKTOP_CHROME), "desktop")

    def test_missing_user_agent(self) -> None:
        self.assertEqual(browsers.family(None), "unknown")
        self.assertEqual(browsers.family(""), "unknown")

    def test_in_app_set_matches_the_families(self) -> None:
        self.assertEqual(browsers.IN_APP, {"wechat", "qq", "douyin", "webview"})


if __name__ == "__main__":
    unittest.main()
