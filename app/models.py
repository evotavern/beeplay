from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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

    # "discover" | "profile" | "feed". Still what the grids are keyed on;
    # ownership now lives in user_id for the profile collection.
    collection: Mapped[str] = mapped_column(index=True)

    # Preserves the fixture ordering so grids stay deterministic.
    position: Mapped[int]

    # Directory name under the games root, i.e. /games/<artifact_hash>/index.html.
    # Null means the work is a fixture with nothing to play. Becomes a foreign
    # key to an artifacts table once generation produces them.
    artifact_hash: Mapped[str | None] = mapped_column(default=None, index=True)

    # Owner, for the profile collection only. Discover and feed rows keep their
    # free-text author and stay null. Nullable because SQLite cannot add a
    # non-null column to the rows already on the deployed database.
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id"), default=None, index=True
    )
