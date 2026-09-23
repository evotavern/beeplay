import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data import CATEGORIES
from app.models import (
    CommentLike,
    User,
    UserFollow,
    Work,
    WorkComment,
    WorkLike,
    WorkSave,
    WorkShare,
    WorkView,
    utcnow,
)

# A claim survives this long past the tester's last request. It is never
# written down as an expiry: `is_claimed` compares, so a claim that has gone
# stale is free the instant it is looked at, with no job to run.
CLAIM_TTL = timedelta(hours=2)

# last_seen_at is only rewritten once it is this stale. Every htmx partial
# fetch would otherwise be a write, and SQLite has a single writer; five
# minutes is invisible against a two hour window.
TOUCH_INTERVAL = timedelta(minutes=5)

COOKIE_NAME = "beeplay_user"


def _with_social_state(
    session: Session, works: list[Work], viewer: User | None
) -> list[Work]:
    """Attach derived social values to work instances for template rendering."""
    if not works:
        return works
    work_ids = [work.id for work in works]

    def counts(model) -> dict[int, int]:
        rows = session.execute(
            select(model.work_id, func.count())
            .where(model.work_id.in_(work_ids))
            .group_by(model.work_id)
        )
        return {work_id: count for work_id, count in rows}

    views = counts(WorkView)
    likes = counts(WorkLike)
    shares = counts(WorkShare)
    comments = counts(WorkComment)
    liked: set[int] = set()
    saved: set[int] = set()
    followed: set[int] = set()
    if viewer is not None:
        liked = set(
            session.scalars(
                select(WorkLike.work_id).where(
                    WorkLike.user_id == viewer.id, WorkLike.work_id.in_(work_ids)
                )
            )
        )
        saved = set(
            session.scalars(
                select(WorkSave.work_id).where(
                    WorkSave.user_id == viewer.id, WorkSave.work_id.in_(work_ids)
                )
            )
        )
        owner_ids = {work.user_id for work in works if work.user_id is not None}
        followed = set(
            session.scalars(
                select(UserFollow.followed_id).where(
                    UserFollow.follower_id == viewer.id,
                    UserFollow.followed_id.in_(owner_ids),
                )
            )
        ) if owner_ids else set()

    for work in works:
        work.view_count = views.get(work.id, 0)
        work.like_count = likes.get(work.id, 0)
        work.share_count = shares.get(work.id, 0)
        work.comment_count = comments.get(work.id, 0)
        work.liked_by_viewer = work.id in liked
        work.saved_by_viewer = work.id in saved
        work.followed_by_viewer = work.user_id in followed
    return works


def _live_works():
    """Works that are publicly playable: the feed, live, with a bundle."""
    return select(Work).where(
        Work.collection == "feed",
        Work.status == "live",
        Work.artifact_hash.is_not(None),
    )


def discover_works(
    session: Session, category: str, viewer: User | None = None
) -> list[Work]:
    """Live playable works shown in discover, newest first."""
    stmt = _live_works()
    if category in CATEGORIES and category != "all":
        stmt = stmt.where(Work.category == category)
    works = list(session.scalars(stmt.order_by(Work.created_at.desc(), Work.id.desc())))
    return _with_social_state(session, works, viewer)


def _owned_by(user: User):
    return select(Work).where(
        Work.collection == "feed", Work.user_id == user.id, Work.status != "deleted"
    )


def profile_works(session: Session, user: User) -> list[Work]:
    """The user's uploads, newest first, including hidden ones."""
    works = list(
        session.scalars(_owned_by(user).order_by(Work.created_at.desc(), Work.id.desc()))
    )
    return _with_social_state(session, works, user)


def liked_works(session: Session, user: User) -> list[Work]:
    works = list(
        session.scalars(
            select(Work)
            .join(WorkLike, WorkLike.work_id == Work.id)
            .where(WorkLike.user_id == user.id, Work.status != "deleted")
            .order_by(WorkLike.created_at.desc())
        )
    )
    return _with_social_state(session, works, user)


def saved_works(session: Session, user: User) -> list[Work]:
    works = list(
        session.scalars(
            select(Work)
            .join(WorkSave, WorkSave.work_id == Work.id)
            .where(WorkSave.user_id == user.id, Work.status != "deleted")
            .order_by(WorkSave.created_at.desc())
        )
    )
    return _with_social_state(session, works, user)


def viewed_works(session: Session, user: User) -> list[Work]:
    latest = (
        select(WorkView.work_id, func.max(WorkView.created_at).label("viewed_at"))
        .where(WorkView.user_id == user.id)
        .group_by(WorkView.work_id)
        .subquery()
    )
    works = list(
        session.scalars(
            select(Work)
            .join(latest, latest.c.work_id == Work.id)
            .where(Work.status != "deleted")
            .order_by(latest.c.viewed_at.desc())
        )
    )
    return _with_social_state(session, works, user)


def works_count(session: Session, user: User) -> int:
    return session.scalar(select(func.count()).select_from(_owned_by(user).subquery()))


def saved_count(session: Session, user: User) -> int:
    return session.scalar(
        select(func.count()).select_from(WorkSave).where(WorkSave.user_id == user.id)
    )


def feed_games(session: Session, viewer: User | None = None) -> list[Work]:
    """Live games, newest first. The status column is the only source of truth."""
    works = list(
        session.scalars(
            _live_works().order_by(Work.created_at.desc(), Work.id.desc())
        )
    )
    return _with_social_state(session, works, viewer)


# --- social interactions --------------------------------------------------


def _live_work(session: Session, work_id: int) -> Work | None:
    return session.scalar(_live_works().where(Work.id == work_id))


def _set_membership(
    session: Session, model, user: User, work_id: int, active: bool
) -> None:
    if _live_work(session, work_id) is None:
        raise LookupError("work not found")
    # Single idempotent statements: a read-then-write would 500 when two tabs
    # or a retry race on the same (user, work) row.
    if active:
        session.execute(
            sqlite_insert(model)
            .values(user_id=user.id, work_id=work_id, created_at=utcnow())
            .on_conflict_do_nothing()
        )
    else:
        session.execute(
            delete(model).where(model.user_id == user.id, model.work_id == work_id)
        )
    session.commit()


def set_like(session: Session, user: User, work_id: int, active: bool) -> tuple[bool, int]:
    _set_membership(session, WorkLike, user, work_id, active)
    total = session.scalar(
        select(func.count()).select_from(WorkLike).where(WorkLike.work_id == work_id)
    )
    return active, total


def set_save(session: Session, user: User, work_id: int, active: bool) -> bool:
    _set_membership(session, WorkSave, user, work_id, active)
    return active


def set_follow(session: Session, user: User, followed_id: int, active: bool) -> bool:
    followed = session.get(User, followed_id)
    if followed is None or followed.id == user.id:
        raise LookupError("user not found")
    if active:
        session.execute(
            sqlite_insert(UserFollow)
            .values(follower_id=user.id, followed_id=followed.id, created_at=utcnow())
            .on_conflict_do_nothing()
        )
    else:
        session.execute(
            delete(UserFollow).where(
                UserFollow.follower_id == user.id, UserFollow.followed_id == followed.id
            )
        )
    session.commit()
    return active


def comments_for_work(session: Session, viewer: User | None, work_id: int) -> list[dict]:
    if _live_work(session, work_id) is None:
        raise LookupError("work not found")
    rows = session.execute(
        select(WorkComment, User)
        .join(User, User.id == WorkComment.user_id)
        .where(WorkComment.work_id == work_id)
        .order_by(WorkComment.created_at.asc(), WorkComment.id.asc())
    ).all()
    comment_ids = [comment.id for comment, _ in rows]
    counts = dict(session.execute(
        select(CommentLike.comment_id, func.count())
        .where(CommentLike.comment_id.in_(comment_ids))
        .group_by(CommentLike.comment_id)
    ).all()) if comment_ids else {}
    liked = set(session.scalars(
        select(CommentLike.comment_id).where(
            CommentLike.user_id == viewer.id, CommentLike.comment_id.in_(comment_ids)
        )
    )) if viewer is not None and comment_ids else set()
    return [{
        "id": comment.id,
        "author": author.name,
        "avatar": author.avatar_fill,
        "content": comment.content,
        "likes": counts.get(comment.id, 0),
        "liked": comment.id in liked,
    } for comment, author in rows]


def add_comment(session: Session, user: User, work_id: int, content: str) -> WorkComment:
    if _live_work(session, work_id) is None:
        raise LookupError("work not found")
    comment = WorkComment(work_id=work_id, user_id=user.id, content=content.strip())
    session.add(comment)
    session.commit()
    session.refresh(comment)
    return comment


def set_comment_like(
    session: Session, user: User, comment_id: int, active: bool
) -> tuple[bool, int]:
    comment = session.get(WorkComment, comment_id)
    if comment is None or _live_work(session, comment.work_id) is None:
        raise LookupError("comment not found")
    if active:
        session.execute(
            sqlite_insert(CommentLike)
            .values(user_id=user.id, comment_id=comment.id, created_at=utcnow())
            .on_conflict_do_nothing()
        )
    else:
        session.execute(delete(CommentLike).where(
            CommentLike.user_id == user.id, CommentLike.comment_id == comment.id
        ))
    session.commit()
    count = session.scalar(
        select(func.count()).select_from(CommentLike).where(CommentLike.comment_id == comment.id)
    )
    return active, count


def record_view(
    session: Session, user: User | None, work_id: int, session_id: str
) -> int:
    if _live_work(session, work_id) is None:
        raise LookupError("work not found")
    session.add(
        WorkView(
            work_id=work_id,
            user_id=user.id if user is not None else None,
            session_id=session_id,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        # Retried delivery of the same mounted play session.
        session.rollback()
    return session.scalar(
        select(func.count()).select_from(WorkView).where(WorkView.work_id == work_id)
    )


def record_share(
    session: Session, user: User | None, work_id: int, event_id: str
) -> int:
    if _live_work(session, work_id) is None:
        raise LookupError("work not found")
    session.add(
        WorkShare(
            work_id=work_id,
            user_id=user.id if user is not None else None,
            event_id=event_id,
        )
    )
    try:
        session.commit()
    except IntegrityError:
        # The client retries with the same idempotency key.
        session.rollback()
    return session.scalar(
        select(func.count()).select_from(WorkShare).where(WorkShare.work_id == work_id)
    )


# --- identities ------------------------------------------------------------


def is_claimed(user: User, now: datetime | None = None) -> bool:
    now = now or utcnow()
    return user.last_seen_at is not None and user.last_seen_at > now - CLAIM_TTL


def all_users(session: Session) -> list[User]:
    """Every claimable identity, in grid order."""
    return list(
        session.scalars(select(User).where(User.claimable).order_by(User.position))
    )


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
    user = session.scalar(select(User).where(User.slug == slug, User.claimable))
    if user is None:
        return None

    now = utcnow()
    holder_token = holder.claim_token if holder is not None else None
    if holder is not None and holder.id == user.id:
        # Already theirs. Refresh rather than reissue, so the cookie they are
        # holding stays valid.
        renewed = session.execute(
            update(User)
            .where(User.id == user.id, User.claim_token == holder_token)
            .values(last_seen_at=now)
        )
        if renewed.rowcount != 1:
            session.rollback()
            return None
        session.commit()
        return holder_token

    # This is a bearer credential, not merely an opaque display ID. 256 bits
    # makes guessing it infeasible even if the claim endpoint is exposed.
    token = secrets.token_hex(32)
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

    # Switching identities frees the old one immediately. Guard the release by
    # the token that authenticated this request: two concurrent requests from
    # one browser must not each reserve a new identity and strand one of them.
    if holder is not None:
        released = session.execute(
            update(User)
            .where(User.id == holder.id, User.claim_token == holder_token)
            .values(last_seen_at=None, claim_token=None)
        )
        if released.rowcount != 1:
            session.rollback()
            return None

    session.commit()
    session.refresh(user)
    return token


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
