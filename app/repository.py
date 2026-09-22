import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from app.data import CATEGORIES
from app.models import User, Work

# A claim survives this long past the tester's last request. It is never
# written down as an expiry: `is_claimed` compares, so a claim that has gone
# stale is free the instant it is looked at, with no job to run.
CLAIM_TTL = timedelta(hours=2)

# last_seen_at is only rewritten once it is this stale. Every htmx partial
# fetch would otherwise be a write, and SQLite has a single writer; five
# minutes is invisible against a two hour window.
TOUCH_INTERVAL = timedelta(minutes=5)

COOKIE_NAME = "beeplay_user"


def utcnow() -> datetime:
    """Naive UTC, because SQLite does not keep a timezone on what it stores."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def discover_works(session: Session, category: str) -> list[Work]:
    """Works shown in discover; 'all' (or anything unknown) returns every one."""
    stmt = select(Work).where(Work.collection == "discover")
    if category in CATEGORIES and category != "all":
        stmt = stmt.where(Work.category == category)
    return list(session.scalars(stmt.order_by(Work.position)))


def profile_works(session: Session, user: User) -> list[Work]:
    return list(
        session.scalars(
            select(Work)
            .where(Work.collection == "profile", Work.user_id == user.id)
            .order_by(Work.position)
        )
    )


def works_count(session: Session, user: User) -> int:
    return session.scalar(
        select(func.count())
        .select_from(Work)
        .where(Work.collection == "profile", Work.user_id == user.id)
    )


def feed_games(session: Session, games_dir: Path) -> list[Work]:
    """Feed records whose static artifact is available to serve."""
    games = session.scalars(
        select(Work)
        .where(Work.collection == "feed", Work.artifact_hash.is_not(None))
        .order_by(Work.position)
    )
    return [
        game
        for game in games
        if (games_dir / game.artifact_hash / "index.html").is_file()
    ]


# --- identities ------------------------------------------------------------


def is_claimed(user: User, now: datetime | None = None) -> bool:
    now = now or utcnow()
    return user.last_seen_at is not None and user.last_seen_at > now - CLAIM_TTL


def all_users(session: Session) -> list[User]:
    return list(session.scalars(select(User).order_by(User.position)))


def next_free_at(session: Session) -> datetime | None:
    """When the longest-idle live claim lapses, or None if one is free now."""
    users = all_users(session)
    live = [user for user in users if is_claimed(user)]
    if len(live) < len(users):
        return None
    return min(user.last_seen_at for user in live) + CLAIM_TTL


def claim(session: Session, slug: str, holder: User | None = None) -> str | None:
    """Take an identity, returning its new claim token, or None if it is taken.

    The guard lives in the UPDATE's WHERE clause rather than in a read followed
    by a write, so two testers tapping the same card at once cannot both win.
    """
    user = session.scalar(select(User).where(User.slug == slug))
    if user is None:
        return None

    now = utcnow()
    if holder is not None and holder.id == user.id:
        # Already theirs. Refresh rather than reissue, so the cookie they are
        # holding stays valid.
        user.last_seen_at = now
        session.commit()
        return user.claim_token

    token = secrets.token_hex(4)
    taken = session.execute(
        update(User)
        .where(
            User.id == user.id,
            or_(User.last_seen_at.is_(None), User.last_seen_at <= now - CLAIM_TTL),
        )
        .values(claim_token=token, last_seen_at=now)
    )
    if taken.rowcount == 0:
        session.rollback()
        return None

    # Switching identities frees the old one immediately: the tester chose to
    # leave, and at a booth the pool is the scarce thing.
    if holder is not None:
        release(session, holder)

    session.commit()
    session.refresh(user)
    return token


def release(session: Session, user: User) -> None:
    user.last_seen_at = None
    user.claim_token = None


def touch(session: Session, user: User) -> None:
    now = utcnow()
    if user.last_seen_at is None or user.last_seen_at <= now - TOUCH_INTERVAL:
        user.last_seen_at = now
        session.commit()


def cookie_value(slug: str, token: str) -> str:
    """The one place the cookie's shape is written down; resolve_cookie reads it."""
    return f"{slug}.{token}"


def resolve_cookie(session: Session, raw: str | None) -> tuple[User | None, str]:
    """Turn a cookie into the current user plus why it failed if it did.

    Status is one of "ok", "anonymous" (no usable cookie) or "stolen" (the
    identity expired while they were away and somebody else took it).
    """
    if not raw or "." not in raw:
        return None, "anonymous"

    slug, _, token = raw.partition(".")
    user = session.scalar(select(User).where(User.slug == slug))
    if user is None:
        return None, "anonymous"

    if user.claim_token != token:
        return None, "stolen" if is_claimed(user) else "anonymous"

    if not is_claimed(user):
        # Their claim lapsed but nobody took it, so let them pick it back up
        # rather than bouncing them to a grid where they would choose it again.
        user.last_seen_at = utcnow()
        session.commit()
        return user, "ok"

    touch(session, user)
    return user, "ok"
