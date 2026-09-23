from sqlalchemy import delete, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.data import CATEGORIES
from app.models import (
    User,
    Work,
    WorkLike,
    WorkSave,
    WorkShare,
    WorkView,
    utcnow,
)

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
    liked: set[int] = set()
    saved: set[int] = set()
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

    for work in works:
        work.view_count = views.get(work.id, 0)
        work.like_count = likes.get(work.id, 0)
        work.share_count = shares.get(work.id, 0)
        work.liked_by_viewer = work.id in liked
        work.saved_by_viewer = work.id in saved
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


def public_works(session: Session, owner: User, viewer: User | None) -> list[Work]:
    """What /u/<handle> shows: only their games that are live in the feed."""
    works = list(
        session.scalars(
            _live_works()
            .where(Work.user_id == owner.id)
            .order_by(Work.created_at.desc(), Work.id.desc())
        )
    )
    return _with_social_state(session, works, viewer)


def likes_received(session: Session, owner: User) -> int:
    return session.scalar(
        select(func.count())
        .select_from(WorkLike)
        .join(Work, Work.id == WorkLike.work_id)
        .where(Work.user_id == owner.id, Work.status == "live")
    )


def user_by_handle(session: Session, slug: str) -> User | None:
    return session.scalar(select(User).where(User.slug == slug.lower()))


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
