from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.data import CATEGORIES
from app.models import Work


def discover_works(session: Session, category: str) -> list[Work]:
    """Works shown in discover; 'all' (or anything unknown) returns every one."""
    stmt = select(Work).where(Work.collection == "discover")
    if category in CATEGORIES and category != "all":
        stmt = stmt.where(Work.category == category)
    return list(session.scalars(stmt.order_by(Work.position)))


def profile_works(session: Session) -> list[Work]:
    return list(
        session.scalars(
            select(Work).where(Work.collection == "profile").order_by(Work.position)
        )
    )


def feed_games(session: Session, games_dir: Path) -> list[Work]:
    """Feed records whose static artifact is available to serve."""
    games = session.scalars(
        select(Work)
        .where(Work.collection == "feed", Work.artifact_hash.is_not(None))
        .order_by(Work.position)
    )
    return [
        game
        for game in games
        if (games_dir / game.artifact_hash / "index.html").is_file()
    ]


def register_imported_game(
    session: Session, *, artifact_hash: str, title: str, author: str = "Jastin Anna"
) -> Work:
    """Add an imported artifact to the existing swipe feed."""
    last_position = session.scalar(
        select(Work.position).where(Work.collection == "feed").order_by(Work.position.desc())
    )
    game = Work(
        artifact_hash=artifact_hash,
        title=title,
        author=author,
        category="relax",
        emoji="🎮",
        art="art-one",
        views="0",
        likes="0",
        collection="feed",
        position=(last_position if last_position is not None else -1) + 1,
    )
    session.add(game)
    session.commit()
    return game
