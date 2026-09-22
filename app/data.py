"""Seed content for the prototype views.

Still hardcoded, but owned by the backend rather than the template's inline
script. These become SQLAlchemy models once the database lands.
"""

WORKS = [
    {"title": "Jungle Escape", "author": "Mia Chen", "category": "relax", "emoji": "🌿", "art": "art-one", "views": "4.9K", "likes": "1.2K"},
    {"title": "Color Keyboard", "author": "Scarlett", "category": "focus", "emoji": "▦", "art": "art-two", "views": "12K", "likes": "3.4K"},
    {"title": "Bounce Lab", "author": "oxo studio", "category": "physics", "emoji": "◌", "art": "art-four", "views": "21K", "likes": "5.1K"},
    {"title": "Swab Logic", "author": "Mia", "category": "puzzle", "emoji": "9", "art": "art-three", "views": "8.8K", "likes": "2.6K"},
    {"title": "Tiny Weather", "author": "Bee Lab", "category": "focus", "emoji": "☁", "art": "art-four", "views": "6.3K", "likes": "1.8K"},
    {"title": "Paper Cut Party", "author": "Skyyyyyy", "category": "relax", "emoji": "✿", "art": "art-three", "views": "2M", "likes": "26K"},
    {"title": "Orbit Catch", "author": "sikramay2.0", "category": "physics", "emoji": "◎", "art": "art-two", "views": "65K", "likes": "8.2K"},
    {"title": "Make 9 Become 6", "author": "Sam", "category": "puzzle", "emoji": "6", "art": "art-one", "views": "1M", "likes": "16K"},
]

# The eight identities a hackathon tester can claim at /claim, in grid order.
# "works" are seeded into the works table as that user's profile collection.
#
# bee-1 is the prototype's original hardcoded profile: the three works already
# sitting in the deployed database are backfilled to her, so nothing is
# orphaned when ownership lands.
USERS = [
    {
        "slug": "bee-1",
        "name": "Jastin Anna",
        "handle": "@jastin_anna",
        "bio": "喜欢把日常任务变成一点点可以玩的东西。",
        "avatar_fill": "d8d6ff",
        "saved_count": 86,
        "level": 1,
        "xp": 450,
        "xp_goal": 1000,
        "works": [
            {"title": "My Focus Island", "category": "focus", "emoji": "☀", "art": "art-one", "views": "128", "likes": "24"},
            {"title": "A Little Bee", "category": "relax", "emoji": "🐝", "art": "art-two", "views": "86", "likes": "19"},
            {"title": "Daily Spark", "category": "puzzle", "emoji": "✦", "art": "art-three", "views": "64", "likes": "12"},
        ],
    },
    {
        "slug": "bee-2",
        "name": "小蜜蜂",
        "handle": "@little_bee",
        "bio": "把每天的小事做成小游戏，做完就很开心。",
        "avatar_fill": "ffe08a",
        "saved_count": 34,
        "level": 2,
        "xp": 620,
        "xp_goal": 1200,
        "works": [
            {"title": "深夜茶馆", "category": "relax", "emoji": "🍵", "art": "art-two", "views": "212", "likes": "41"},
            {"title": "一只猫的下午", "category": "relax", "emoji": "🐱", "art": "art-three", "views": "158", "likes": "37"},
        ],
    },
    {
        "slug": "bee-3",
        "name": "阿尔法",
        "handle": "@alpha_lab",
        "bio": "在做一些奇怪的物理实验，偶尔能玩。",
        "avatar_fill": "a8e6cf",
        "saved_count": 51,
        "level": 3,
        "xp": 180,
        "xp_goal": 1500,
        "works": [
            {"title": "弹力实验室", "category": "physics", "emoji": "◌", "art": "art-four", "views": "934", "likes": "126"},
            {"title": "重力糖果", "category": "physics", "emoji": "◎", "art": "art-one", "views": "402", "likes": "88"},
            {"title": "斜坡与球", "category": "physics", "emoji": "▲", "art": "art-two", "views": "221", "likes": "30"},
        ],
    },
    {
        "slug": "bee-4",
        "name": "林夕",
        "handle": "@linxi_makes",
        "bio": "专注三十分钟，然后奖励自己一局。",
        "avatar_fill": "ffb3ba",
        "saved_count": 12,
        "level": 1,
        "xp": 240,
        "xp_goal": 1000,
        "works": [
            {"title": "番茄小岛", "category": "focus", "emoji": "🍅", "art": "art-one", "views": "76", "likes": "15"},
            {"title": "安静的雨", "category": "relax", "emoji": "☂", "art": "art-three", "views": "310", "likes": "64"},
        ],
    },
    {
        "slug": "bee-5",
        "name": "甜豆",
        "handle": "@sweetbean",
        "bio": "喜欢配色，做的东西都甜甜的。",
        "avatar_fill": "ffd1a9",
        "saved_count": 73,
        "level": 2,
        "xp": 890,
        "xp_goal": 1200,
        "works": [
            {"title": "糖果排排站", "category": "puzzle", "emoji": "🍬", "art": "art-four", "views": "1.1K", "likes": "203"},
            {"title": "颜色小键盘", "category": "focus", "emoji": "▦", "art": "art-two", "views": "845", "likes": "97"},
        ],
    },
    {
        "slug": "bee-6",
        "name": "老陈",
        "handle": "@chen_studio",
        "bio": "做了十年工具，最近想做点没用但好玩的。",
        "avatar_fill": "b5d8ff",
        "saved_count": 8,
        "level": 4,
        "xp": 60,
        "xp_goal": 2000,
        "works": [
            {"title": "九变成六", "category": "puzzle", "emoji": "6", "art": "art-one", "views": "2.4K", "likes": "318"},
            {"title": "一格一格", "category": "puzzle", "emoji": "▩", "art": "art-three", "views": "620", "likes": "74"},
            {"title": "每天一题", "category": "focus", "emoji": "✎", "art": "art-four", "views": "199", "likes": "22"},
        ],
    },
    {
        "slug": "bee-7",
        "name": "柚子",
        "handle": "@yuzu_play",
        "bio": "手机上三分钟能玩完的，才是好游戏。",
        "avatar_fill": "c8f7c5",
        "saved_count": 45,
        "level": 2,
        "xp": 410,
        "xp_goal": 1200,
        "works": [
            {"title": "柚子跳跳", "category": "physics", "emoji": "🍋", "art": "art-two", "views": "533", "likes": "81"},
            {"title": "三分钟冥想", "category": "relax", "emoji": "❁", "art": "art-one", "views": "287", "likes": "52"},
        ],
    },
    {
        "slug": "bee-8",
        "name": "麦田",
        "handle": "@wheatfield",
        "bio": "想把一整个夏天做成一个可以打开的东西。",
        "avatar_fill": "e0c3fc",
        "saved_count": 27,
        "level": 1,
        "xp": 700,
        "xp_goal": 1000,
        "works": [
            {"title": "夏天的风", "category": "relax", "emoji": "🌾", "art": "art-three", "views": "168", "likes": "39"},
            {"title": "云朵天气", "category": "focus", "emoji": "☁", "art": "art-four", "views": "94", "likes": "18"},
        ],
    },
]


# Playable games in the home feed. Seeded by hand while generation does not
# exist yet; artifact_hash is the directory under the games root.
FEED_GAMES = [
    {
        "title": "今日咖啡心情",
        "author": "MOOD CAFÉ",
        "category": "relax",
        "emoji": "☕",
        "art": "art-one",
        "views": "0",
        "likes": "0",
        "artifact_hash": "af359667cf6a8038",
    },
]


PROFILE_TABS = {
    "works": None,
    "likes": "还没有喜欢的作品",
    "saved": "收藏夹还是空的",
    "history": "还没有浏览记录",
}

CATEGORIES = ("all", "focus", "relax", "physics", "puzzle")
