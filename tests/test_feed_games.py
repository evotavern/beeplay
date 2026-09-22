import tempfile
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Work
from app.repository import feed_games


class FeedGamesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite://")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.session.add_all(
            [
                Work(
                    artifact_hash="ready-game",
                    title="Ready",
                    author="Bee",
                    category="relax",
                    emoji="🎮",
                    art="art-one",
                    views="0",
                    likes="0",
                    position=0,
                    collection="feed",
                ),
                Work(
                    artifact_hash="missing-game",
                    title="Missing",
                    author="Bee",
                    category="relax",
                    emoji="🎮",
                    art="art-one",
                    views="0",
                    likes="0",
                    position=1,
                    collection="feed",
                ),
                Work(
                    artifact_hash="not-feed-game",
                    title="Not a feed game",
                    author="Bee",
                    category="relax",
                    emoji="🎮",
                    art="art-one",
                    views="0",
                    likes="0",
                    position=2,
                    collection="discover",
                ),
            ]
        )
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_only_advertises_feed_games_with_an_index_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            game_dir = Path(directory) / "ready-game"
            game_dir.mkdir()
            (game_dir / "index.html").write_text("<!doctype html>")
            not_feed_dir = Path(directory) / "not-feed-game"
            not_feed_dir.mkdir()
            (not_feed_dir / "index.html").write_text("<!doctype html>")

            self.assertEqual(
                [game.title for game in feed_games(self.session, Path(directory))],
                ["Ready"],
            )


if __name__ == "__main__":
    unittest.main()
