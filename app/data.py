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

PROFILE_WORKS = [
    {"title": "My Focus Island", "author": "Jastin Anna", "category": "focus", "emoji": "☀", "art": "art-one", "views": "128", "likes": "24"},
    {"title": "A Little Bee", "author": "Jastin Anna", "category": "relax", "emoji": "🐝", "art": "art-two", "views": "86", "likes": "19"},
    {"title": "Daily Spark", "author": "Jastin Anna", "category": "puzzle", "emoji": "✦", "art": "art-three", "views": "64", "likes": "12"},
]


PROFILE_TABS = {
    "works": None,
    "likes": "还没有喜欢的作品",
    "saved": "收藏夹还是空的",
    "history": "还没有浏览记录",
}

CATEGORIES = ("all", "focus", "relax", "physics", "puzzle")


def works_for(category: str) -> list[dict]:
    """Works in a discover category; 'all' (or anything unknown) returns every work."""
    if category not in CATEGORIES or category == "all":
        return WORKS
    return [work for work in WORKS if work["category"] == category]
