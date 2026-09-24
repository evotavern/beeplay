from datetime import datetime, timezone

from sqlalchemy import ForeignKey, Text, UniqueConstraint, false, true
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

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
    """A person's account, created silently the first time they need one.

    Nobody signs up: the first like, save, creation or visit to /profile makes
    an account with an automatic name and handle and a session cookie for this
    device. Setting a password (which locks the handle) is what lets the same
    person log in on another device.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)

    # The @handle, lowercase a-z 0-9 _, used in /u/<slug> and in login.
    # Automatic ("bee482193") until the owner picks one, which they can do
    # exactly once; see handle_locked.
    slug: Mapped[str] = mapped_column(unique=True, index=True)
    handle_locked: Mapped[bool] = mapped_column(default=False, server_default=false())

    name: Mapped[str]
    bio: Mapped[str] = mapped_column(default="", server_default="")

    # Hex without the leading '#'. The one inline avatar SVG is recolored per
    # user; avatar_path, when set, is an uploaded photo and wins.
    avatar_fill: Mapped[str]
    # File name under AVATARS_DIR, e.g. "3f2a9c0d1e2b4a5c.webp".
    avatar_path: Mapped[str | None] = mapped_column(default=None)

    # Progression is still a prototype placeholder: every account shows
    # these defaults and nothing earns XP yet.
    level: Mapped[int] = mapped_column(default=1, server_default="1")
    xp: Mapped[int] = mapped_column(default=0, server_default="0")
    xp_goal: Mapped[int] = mapped_column(default=1000, server_default="1000")

    # argon2. Null until the owner sets one; without it the account lives
    # only in this device's session cookie.
    password_hash: Mapped[str | None] = mapped_column(default=None)

    # A staff-issued one-time reset link (beeplay-ops reset-password): the
    # sha256 of the token and when it stops working.
    reset_token_hash: Mapped[str | None] = mapped_column(default=None, index=True)
    reset_expires_at: Mapped[datetime | None] = mapped_column(default=None)

    # Set once the "pick a name" prompt after a first publish was shown, so
    # it is asked exactly once whatever the answer.
    profile_prompted: Mapped[bool] = mapped_column(default=False, server_default=false())

    # False only for the house account that owns the team's own games: it
    # never gets a session and cannot be logged into.
    loginable: Mapped[bool] = mapped_column(default=True, server_default=true())

    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    @property
    def handle(self) -> str:
        return "@" + self.slug


class UserSession(Base):
    """One device's login. The cookie holds the token; only its hash is kept."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    # Refreshed at most every TOUCH_INTERVAL, so reads stay reads.
    last_seen_at: Mapped[datetime] = mapped_column(default=utcnow)


class Work(Base):
    """A playable work in the feed."""

    __tablename__ = "works"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    author: Mapped[str]
    category: Mapped[str] = mapped_column(index=True)
    emoji: Mapped[str]
    art: Mapped[str]

    # Every real game is "feed"; the fake discover/profile rows were deleted
    # by migration 0003.
    collection: Mapped[str] = mapped_column(index=True)

    # Unused by the feed, which orders newest first; kept for the old rows.
    position: Mapped[int] = mapped_column(default=0)

    # The directory currently served, /games/<artifact_hash>/index.html.
    # Replacing a game points this at a new directory; the old one stays on
    # disk and the swap is recorded in work_events.
    artifact_hash: Mapped[str | None] = mapped_column(default=None, index=True)

    # The account that uploaded it, or the house account. `author` above is
    # the name at publish time, kept for history; pages show owner.name.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), default=None, index=True
    )
    owner: Mapped[User | None] = relationship(lazy="selectin")

    # One of STATUSES. The source of truth for what is shown; the games
    # directory is never consulted.
    status: Mapped[str] = mapped_column(default="live", server_default="live", index=True)

    description: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class WorkLike(Base):
    """A user's current like state for a work."""

    __tablename__ = "work_likes"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    work_id: Mapped[int] = mapped_column(
        ForeignKey("works.id"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class WorkSave(Base):
    """A work in a user's private saved collection."""

    __tablename__ = "work_saves"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    work_id: Mapped[int] = mapped_column(
        ForeignKey("works.id"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class WorkView(Base):
    """One newly mounted play session; pause/resume keeps the same session."""

    __tablename__ = "work_views"
    __table_args__ = (UniqueConstraint("work_id", "session_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), default=None, index=True
    )
    # Minted by the host for a newly mounted game. Retries are idempotent.
    session_id: Mapped[str] = mapped_column(index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class WorkShare(Base):
    """A completed native share or successful clipboard fallback."""

    __tablename__ = "work_shares"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), default=None, index=True
    )
    # Client idempotency key: a retry must not inflate the aggregate.
    event_id: Mapped[str] = mapped_column(unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class UserFollow(Base):
    """A follow between two of the eight claimed demo identities."""

    __tablename__ = "user_follows"

    follower_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    followed_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True, index=True)
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class WorkComment(Base):
    """A persisted comment on a live work."""

    __tablename__ = "work_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=utcnow, index=True)


class CommentLike(Base):
    """A demo identity's like on a comment."""

    __tablename__ = "comment_likes"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    comment_id: Mapped[int] = mapped_column(
        ForeignKey("work_comments.id"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)


class WorkEvent(Base):
    """Append-only audit trail of every change to a work. Never pruned."""

    __tablename__ = "work_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    work_id: Mapped[int] = mapped_column(ForeignKey("works.id"), index=True)
    # "user:<id>" (older rows: "user:<slug>"), "ops:<unix user>" or "system".
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


class Generation(Base):
    __tablename__ = "generations"
    id: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    prompt: Mapped[str] = mapped_column(Text)
    model: Mapped[str]
    # "touch", or "head": played with head movements through the camera.
    controls: Mapped[str] = mapped_column(default="touch", server_default="touch")
    status: Mapped[str] = mapped_column(default="queued", index=True)
    details: Mapped[str] = mapped_column(Text, default="{}")
    html: Mapped[str | None] = mapped_column(Text, default=None)
    error: Mapped[str | None] = mapped_column(default=None)
    timings: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(default=None)
    details_at: Mapped[datetime | None] = mapped_column(default=None)
    playtest_at: Mapped[datetime | None] = mapped_column(default=None)
    work_id: Mapped[int | None] = mapped_column(ForeignKey("works.id"), default=None)


class GenerationEvent(Base):
    __tablename__ = "generation_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    generation_id: Mapped[str] = mapped_column(ForeignKey("generations.id"), index=True)
    kind: Mapped[str]
    elapsed_ms: Mapped[int | None] = mapped_column(default=None)
    at: Mapped[datetime] = mapped_column(default=utcnow)


class GenerationKey(Base):
    __tablename__ = "generation_keys"
    id: Mapped[str] = mapped_column(primary_key=True)
    disabled: Mapped[bool] = mapped_column(default=False)
    cooldown_until: Mapped[datetime | None] = mapped_column(default=None)
    last_used_at: Mapped[datetime | None] = mapped_column(default=None)


class GenerationAttempt(Base):
    __tablename__ = "generation_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    generation_id: Mapped[str] = mapped_column(ForeignKey("generations.id"), index=True)
    key_id: Mapped[str]
    model: Mapped[str]
    status: Mapped[str]
    http_status: Mapped[int | None] = mapped_column(default=None)
    # Classified refusal, e.g. model_not_allowed; see generation.rejection_reason.
    reason: Mapped[str | None] = mapped_column(default=None)
    latency_ms: Mapped[int] = mapped_column(default=0)
    usage: Mapped[str] = mapped_column(Text, default="{}")
    limits: Mapped[str] = mapped_column(Text, default="{}")
    at: Mapped[datetime] = mapped_column(default=utcnow)
