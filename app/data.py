"""Seed content for the prototype views.

Still hardcoded, but owned by the backend rather than the template's inline
script. These become SQLAlchemy models once the database lands.
"""

# The eight identities a hackathon tester can claim at /claim, in grid order.
USERS = [
    {
        "slug": "bee-1",
        "name": "Jastin Anna",
        "handle": "@jastin_anna",
        "bio": "喜欢把日常任务变成一点点可以玩的东西。",
        "avatar_fill": "d8d6ff",
        "level": 1,
        "xp": 450,
        "xp_goal": 1000,
    },
    {
        "slug": "bee-2",
        "name": "小蜜蜂",
        "handle": "@little_bee",
        "bio": "把每天的小事做成小游戏，做完就很开心。",
        "avatar_fill": "ffe08a",
        "level": 2,
        "xp": 620,
        "xp_goal": 1200,
    },
    {
        "slug": "bee-3",
        "name": "阿尔法",
        "handle": "@alpha_lab",
        "bio": "在做一些奇怪的物理实验，偶尔能玩。",
        "avatar_fill": "a8e6cf",
        "level": 3,
        "xp": 180,
        "xp_goal": 1500,
    },
    {
        "slug": "bee-4",
        "name": "林夕",
        "handle": "@linxi_makes",
        "bio": "专注三十分钟，然后奖励自己一局。",
        "avatar_fill": "ffb3ba",
        "level": 1,
        "xp": 240,
        "xp_goal": 1000,
    },
    {
        "slug": "bee-5",
        "name": "甜豆",
        "handle": "@sweetbean",
        "bio": "喜欢配色，做的东西都甜甜的。",
        "avatar_fill": "ffd1a9",
        "level": 2,
        "xp": 890,
        "xp_goal": 1200,
    },
    {
        "slug": "bee-6",
        "name": "老陈",
        "handle": "@chen_studio",
        "bio": "做了十年工具，最近想做点没用但好玩的。",
        "avatar_fill": "b5d8ff",
        "level": 4,
        "xp": 60,
        "xp_goal": 2000,
    },
    {
        "slug": "bee-7",
        "name": "柚子",
        "handle": "@yuzu_play",
        "bio": "手机上三分钟能玩完的，才是好游戏。",
        "avatar_fill": "c8f7c5",
        "level": 2,
        "xp": 410,
        "xp_goal": 1200,
    },
    {
        "slug": "bee-8",
        "name": "麦田",
        "handle": "@wheatfield",
        "bio": "想把一整个夏天做成一个可以打开的东西。",
        "avatar_fill": "e0c3fc",
        "level": 1,
        "xp": 700,
        "xp_goal": 1000,
    },
]

# Owns the team's own games. Not claimable, so never in the claim grid.
HOUSE_USER = {
    "slug": "beeplay",
    "name": "蜂玩 BeePlay",
    "handle": "@beeplay",
    "bio": "蜂玩团队的官方作品。",
    "avatar_fill": "c8f05a",
    "level": 1,
    "xp": 0,
    "xp_goal": 1000,
}


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
