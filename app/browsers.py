"""Coarse browser family from a User-Agent, recorded on every failure event.

In-app browsers (WeChat and friends) are where most compatibility surprises
come from, so they get their own families; everything else is just mobile or
desktop. Order matters: WeChat on Android also says "; wv)".
"""

import re

IN_APP = {"wechat", "qq", "douyin", "webview"}

_RULES = (
    ("wechat", re.compile(r"MicroMessenger", re.IGNORECASE)),
    ("qq", re.compile(r"\bQQ/|MQQBrowser")),
    ("douyin", re.compile(r"aweme|BytedanceWebview|Douyin", re.IGNORECASE)),
    # Android WebView marks itself with "; wv)"; an iOS in-app browser is
    # WebKit on an iPhone/iPad without Safari's own token.
    ("webview", re.compile(r"; wv\)|(iPhone|iPad).*AppleWebKit(?!.*Safari/)")),
    ("mobile", re.compile(r"Mobile|Android|iPhone|iPad")),
)


def family(user_agent: str | None) -> str:
    if not user_agent:
        return "unknown"
    for name, pattern in _RULES:
        if pattern.search(user_agent):
            return name
    return "desktop"


def fields(user_agent: str | None) -> dict:
    """The browser fields every failure event carries."""
    return {"browser": family(user_agent), "ua": (user_agent or "")[:300] or None}
