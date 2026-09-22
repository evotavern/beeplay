from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


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

    # "discover" | "profile". Interim stand-in for ownership — replaced by a
    # foreign key to the author once users exist.
    collection: Mapped[str] = mapped_column(index=True)

    # Preserves the fixture ordering so grids stay deterministic.
    position: Mapped[int]
