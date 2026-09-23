"""Profile pictures: an uploaded photo, or the one drawing re-tinted per account.

The prototype inlined one SVG data URI in the templates. Accounts without a
photo still need to tell each other apart at a glance, so the same drawing is
recolored rather than shipping an image per person.
"""

_TEMPLATE = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 120 120'%3E"
    "%3Crect width='120' height='120' rx='36' fill='%23{fill}'/%3E"
    "%3Ccircle cx='61' cy='47' r='24' fill='%23171b1a'/%3E"
    "%3Cpath d='M25 108c5-28 22-43 37-43s32 15 37 43' fill='%23{accent}'/%3E"
    "%3Ccircle cx='53' cy='43' r='4' fill='%23fff'/%3E%3C/svg%3E"
)

# The prototype's orange shirt, kept for every account so the recolor reads as
# the same character rather than eight unrelated drawings.
ACCENT = "f27c45"


def avatar(fill: str = "d8d6ff") -> str:
    return _TEMPLATE.format(fill=fill, accent=ACCENT)


def user_avatar(user) -> str:
    """What an <img src> shows for this account; the default drawing for None."""
    if user is None:
        return avatar()
    if user.avatar_path:
        return "/avatars/" + user.avatar_path
    return avatar(user.avatar_fill)
