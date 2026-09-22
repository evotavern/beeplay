import os
from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.data import FEED_GAMES, USERS, WORKS
from app.models import Base, User, Work

BASE_DIR = Path(__file__).resolve().parent.parent
# Deployed, the app directory is read-only and state belongs in
# /var/lib/beeplay; locally it just sits next to the code.
DB_PATH = Path(os.environ.get("BEEPLAY_DB_PATH", BASE_DIR / "beeplay.db"))

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    # FastAPI runs `def` endpoints in a threadpool, so a pooled connection can
    # be handed to a different thread than the one that opened it.
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragmas(dbapi_connection, connection_record) -> None:
    """SQLite's defaults are wrong for a web app; set them on every connection.

    WAL lets readers work while the single writer is busy, busy_timeout waits
    for that writer instead of raising "database is locked", and foreign key
    enforcement is off by default in SQLite.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def _ensure_work_user_id() -> None:
    """Add works.user_id to a database that predates ownership.

    create_all() creates missing tables but never alters existing ones, and the
    deployed database already has a works table. Checking the column is what
    keeps a restart self-migrating, with no step for an operator to forget.
    SQLite cannot attach a REFERENCES clause when adding a column, so the
    foreign key stays declarative on the model.
    """
    with engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.exec_driver_sql("PRAGMA table_info(works)")
        }
        if "user_id" not in columns:
            connection.exec_driver_sql("ALTER TABLE works ADD COLUMN user_id INTEGER")


def _adopt_orphan_profile_works(session: Session, user: User) -> bool:
    """Give the prototype's ownerless profile works to the first identity.

    The deployed database already holds three profile works from before
    ownership existed. Adopting them is what keeps the first persona from
    ending up with both those rows and a fresh copy of the same fixtures.
    Returns whether anything was adopted; on a fresh database, nothing is.
    """
    adopted = session.execute(
        update(Work)
        .where(Work.collection == "profile", Work.user_id.is_(None))
        .values(user_id=user.id, author=user.name)
    )
    return adopted.rowcount > 0


def _seed_users(session: Session) -> None:
    """Insert any identity that is missing, keyed on slug.

    Guarded per user rather than on an empty table: the works table on the
    deployed database is already full, so an "is it empty" guard would skip
    every persona's works exactly the way the old fixture guard skipped
    everything else.
    """
    existing = set(session.scalars(select(User.slug)))
    first = True
    for position, fixture in enumerate(USERS):
        if fixture["slug"] in existing:
            first = False
            continue
        user = User(
            **{key: value for key, value in fixture.items() if key != "works"},
            position=position,
        )
        session.add(user)
        session.flush()
        if not (first and _adopt_orphan_profile_works(session, user)):
            session.add_all(
                [
                    Work(
                        collection="profile",
                        position=index,
                        author=user.name,
                        user_id=user.id,
                        **work,
                    )
                    for index, work in enumerate(fixture["works"])
                ]
            )
        first = False
    session.commit()


def _seed_works(session: Session) -> None:
    """Seed the collections that are not owned by anyone."""
    for collection, fixtures in (("discover", WORKS), ("feed", FEED_GAMES)):
        if session.scalar(
            select(func.count())
            .select_from(Work)
            .where(Work.collection == collection)
        ):
            continue
        session.add_all(
            [
                Work(collection=collection, position=position, **fixture)
                for position, fixture in enumerate(fixtures)
            ]
        )
    session.commit()


def init_db() -> None:
    """Create tables, migrate the one added column, and seed what is missing."""
    Base.metadata.create_all(engine)
    _ensure_work_user_id()
    with SessionLocal() as session:
        _seed_works(session)
        _seed_users(session)
