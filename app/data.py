"""Fixed content: the house account, the first feed game, UI constants."""

# Colours a new account is given at random and can later pick from. The
# first eight are the old tester identities' colours.
AVATAR_FILLS = (
    "d8d6ff", "ffe08a", "a8e6cf", "ffb3ba", "ffd1a9", "b5d8ff", "c8f7c5", "e0c3fc",
)

# Owns the team's own games. Not loginable, so never gets a session.
HOUSE_USER = {
    "slug": "beeplay",
    "name": "蜂玩 BeePlay",
    "bio": "蜂玩团队的官方作品。",
    "avatar_fill": "c8f05a",
}

# Handles nobody can pick. bee-1..8 cannot be typed anyway (no hyphens).
RESERVED_HANDLES = frozenset({
    "beeplay", "admin", "administrator", "root", "staff", "ops", "system",
    "support", "help", "official", "api", "u", "login", "logout", "profile",
    "claim", "reset", "games", "assets", "avatars",
})


# Seeded into an empty feed only, owned by the house account, so a fresh
# checkout has one game to play. artifact_hash is the directory under the
# games root.
FEED_GAMES = [
    {
        "title": "今日咖啡心情",
        "author": "MOOD CAFÉ",
        "category": "relax",
        "emoji": "☕",
        "art": "art-one",
        "artifact_hash": "af359667cf6a8038",
    },
]


PROFILE_TABS = {
    "works": "还没有发布作品",
    "likes": "还没有喜欢的作品",
    "saved": "收藏夹还是空的",
    "history": "还没有浏览记录",
}

CATEGORIES = ("all", "focus", "relax", "physics", "puzzle")
