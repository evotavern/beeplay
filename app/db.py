import os
from collections.abc import Iterator
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, func, inspect, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.data import FEED_GAMES, HOUSE_USER, USERS
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
HEAD_REVISION = "0003"


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


def _seed_users(session: Session) -> None:
    """Insert any identity that is missing, keyed on slug."""
    existing = set(session.scalars(select(User.slug)))
    for position, fixture in enumerate(USERS):
        if fixture["slug"] not in existing:
            session.add(User(**fixture, position=position))
    if HOUSE_USER["slug"] not in existing:
        session.add(User(**HOUSE_USER, position=len(USERS), claimable=False))
    session.commit()


def _seed_feed(session: Session) -> None:
    """Give ownerless feed games to the house account; seed an empty feed."""
    house = session.scalar(select(User).where(User.slug == HOUSE_USER["slug"]))
    session.execute(
        update(Work)
        .where(Work.collection == "feed", Work.user_id.is_(None))
        .values(user_id=house.id)
    )
    if not session.scalar(select(func.count()).select_from(Work)):
        session.add_all(
            Work(collection="feed", user_id=house.id, **fixture) for fixture in FEED_GAMES
        )
    session.commit()


def init_db() -> None:
    """Migrate the schema, then seed what is missing."""
    migrate()
    with SessionLocal() as session:
        _seed_users(session)
        _seed_feed(session)
