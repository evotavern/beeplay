import unittest
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Work
from app.repository import feed_games


def game(title: str, minute: int, status: str = "live", collection: str = "feed") -> Work:
    return Work(
        artifact_hash=f"{title}-artifact",
        title=title,
        author="Bee",
        category="relax",
        emoji="🎮",
        art="art-one",
        collection=collection,
        status=status,
        created_at=datetime(2026, 9, 23, 12, minute),
    )


class FeedGamesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_shows_only_live_games_newest_first(self) -> None:
        self.session.add_all(
            [
                game("Older", 0),
                game("Newer", 5),
                game("Crashing", 6, status="hidden"),
                game("Test build", 7, status="unlisted"),
                game("Removed", 8, status="deleted"),
            ]
        )
        self.session.commit()

        self.assertEqual([g.title for g in feed_games(self.session)], ["Newer", "Older"])

    def test_a_live_game_is_listed_whether_or_not_its_files_exist(self) -> None:
        # Missing files are caught by the load timeout, not by the listing.
        self.session.add(game("No files anywhere", 0))
        self.session.commit()

        self.assertEqual([g.title for g in feed_games(self.session)], ["No files anywhere"])


if __name__ == "__main__":
    unittest.main()
