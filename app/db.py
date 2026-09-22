from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.data import PROFILE_WORKS, WORKS
from app.models import Base, Work

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "beeplay.db"

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


def init_db() -> None:
    """Create tables and seed the prototype fixtures once."""
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        if session.scalar(select(func.count()).select_from(Work)):
            return
        session.add_all(
            [
                Work(collection=collection, position=position, **fixture)
                for collection, fixtures in (("discover", WORKS), ("profile", PROFILE_WORKS))
                for position, fixture in enumerate(fixtures)
            ]
        )
        session.commit()
