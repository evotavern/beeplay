from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Text, true
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# live: in the public feed. hidden: pulled by an operator or auto-hidden for
# crashing; the owner still sees it. unlisted: test games, reachable by link.
# deleted: gone from every list; the artifact stays on disk.
STATUSES = ("live", "hidden", "unlisted", "deleted")


def utcnow() -> datetime:
    """Naive UTC, because SQLite does not keep a timezone on what it stores."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    """A pre-seeded identity a hackathon tester can claim.

    There is no authentication: a tester picks an identity from /claim and the
    server hands back a cookie. Claims are exclusive but self-releasing, which
    is what `last_seen_at` is for -- see `repository.is_claimed`.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    # Stable handle used in URLs and in the cookie ("bee-3"), so a printed QR
    # code survives a reseed that renumbers the primary keys.
    slug: Mapped[str] = mapped_column(unique=True, index=True)

    name: Mapped[str]
    handle: Mapped[str]
    bio: Mapped[str]

    # Hex without the leading '#'. The one inline avatar SVG is recolored per
    # user rather than shipping eight images.
    avatar_fill: Mapped[str]

    # Profile card numbers with no system behind them yet. The works count is
    # derived from the works table; these three stay fixtures so that two
    # testers side by side still see different cards.
    saved_count: Mapped[int]
    level: Mapped[int]
    xp: Mapped[int]
    xp_goal: Mapped[int]

    # Ordering of the claim grid, same role as Work.position.
    position: Mapped[int]

    # Regenerated on every claim. It lets a returning cookie prove it is the
    # same tester rather than someone who took the identity after it expired.
    claim_token: Mapped[str | None] = mapped_column(default=None)

    # Naive UTC. Null means never claimed; otherwise the claim is live until
    # CLAIM_TTL after this moment, so expiry is a comparison and not a job.
    last_seen_at: Mapped[datetime | None] = mapped_column(default=None)

    # False for the house account that owns the team's own games: it never
    # appears in the claim grid and cannot be claimed.
    claimable: Mapped[bool] = mapped_column(default=True, server_default=true())


class Work(Base):
    """A playable work in the feed."""

    __tablename__ = "works"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    author: Mapped[str]
    category: Mapped[str] = mapped_column(index=True)
    emoji: Mapped[str]
    art: Mapped[str]

    # Display strings ("4.9K"), exactly as the prototype showed them. These
    # become counts derived from an interaction events table once the
    # interactions are real rather than fixtures.
    views: Mapped[str]
    likes: Mapped[str]

    # Every real game is "feed"; the fake discover/profile rows were deleted
    # by migration 0003.
    collection: Mapped[str] = mapped_column(index=True)

    # Unused by the feed, which orders newest first; kept for the old rows.
    position: Mapped[int] = mapped_column(default=0)

    # The directory currently served, /games/<artifact_hash>/index.html.
    # Replacing a game points this at a new directory; the old one stays on
    # disk and the swap is recorded in work_events.
    artifact_hash: Mapped[str | None] = mapped_column(default=None, index=True)

    # The claimed identity that uploaded it, or the house account.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), default=None, index=True
    )

    # One of STATUSES. The source of truth for what is shown; the games
    # directory is never consulted.
    status: Mapped[str] = mapped_column(default="live", server_default="live", index=True)

    description: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class WorkEvent(Base):
    """Append-only audit trail of every change to a work. Never pruned."""

    __tablename__ = "work_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"), index=True)
    # "user:<slug>", "ops:<unix user>" or "system".
    actor: Mapped[str]
    # created | artifact_replaced | status_changed | metadata_changed
    kind: Mapped[str]
    # JSON of the changed fields.
    before: Mapped[str | None] = mapped_column(Text, default=None)
    after: Mapped[str | None] = mapped_column(Text, default=None)
    at: Mapped[datetime] = mapped_column(default=utcnow)


class HealthEvent(Base):
    """One signal from one play of one game. Noisy; safe to prune."""

    __tablename__ = "health_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"), index=True)
    # Reports about an artifact that has since been replaced are kept but
    # never count against the new one.
    artifact_hash: Mapped[str]
    # Random per play, minted by the browser when the game is mounted.
    session_id: Mapped[str] = mapped_column(index=True)
    # start | loaded | error | timeout
    kind: Mapped[str]
    # Milliseconds since the game was mounted.
    elapsed_ms: Mapped[int | None] = mapped_column(default=None)
    detail: Mapped[str | None] = mapped_column(Text, default=None)
    at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class FailedUpload(Base):
    """A bundle that failed validation, kept so an operator can fix it."""

    __tablename__ = "failed_uploads"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), default=None)
    title: Mapped[str]
    category: Mapped[str]
    emoji: Mapped[str]
    art: Mapped[str]
    description: Mapped[str | None] = mapped_column(default=None)
    error: Mapped[str]
    # The raw upload as a zip, under the failed-uploads directory.
    stored_path: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    # Set once an operator has fixed and inserted it.
    resolved_work_id: Mapped[int | None] = mapped_column(
        ForeignKey("works.id"), default=None
    )
