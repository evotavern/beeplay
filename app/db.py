import os
from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, func, inspect, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.data import FEED_GAMES, USERS, WORKS
from app.models import User, Work

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


MIGRATIONS_DIR = BASE_DIR / "migrations"
HEAD_REVISION = "0002"


def _stamp_unversioned(connection) -> str | None:
    """Revision an existing database is at when it predates Alembic.

    Both shapes that exist in the wild are recognised: the first deployment
    (works only) and the claiming branch (works + users, built by create_all).
    """
    tables = set(inspect(connection).get_table_names())
    if "alembic_version" in tables or "works" not in tables:
        return None
    return "0002" if "users" in tables else "0001"


def migrate(target_engine=None, target: str = "head") -> None:
    """Bring the schema up to date. Safe to run on every startup."""
    target_engine = target_engine or engine
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    with target_engine.connect() as connection:
        # Batch migrations rebuild tables by copy-and-swap, which foreign key
        # enforcement would reject midway. The pragma only takes effect
        # outside a transaction, hence before begin().
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.commit()
        config.attributes["connection"] = connection
        legacy = _stamp_unversioned(connection)
        if legacy:
            command.stamp(config, legacy)
        command.upgrade(config, target)
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")


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
    """Migrate the schema, then seed what is missing."""
    migrate()
    with SessionLocal() as session:
        _seed_works(session)
        _seed_users(session)
