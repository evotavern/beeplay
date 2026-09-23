import tempfile
import unittest
from pathlib import Path

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.db import HEAD_REVISION, migrate
from app.models import Base

# The works table exactly as the first deployment created it, before Alembic.
LEGACY_WORKS = """
CREATE TABLE works (
    id INTEGER NOT NULL, title VARCHAR NOT NULL, author VARCHAR NOT NULL,
    category VARCHAR NOT NULL, emoji VARCHAR NOT NULL, art VARCHAR NOT NULL,
    views VARCHAR NOT NULL, likes VARCHAR NOT NULL, collection VARCHAR NOT NULL,
    position INTEGER NOT NULL, artifact_hash VARCHAR, PRIMARY KEY (id)
)
"""


class MigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.engine = create_engine(f"sqlite:///{Path(self.directory.name) / 'test.db'}")

    def tearDown(self) -> None:
        self.engine.dispose()
        self.directory.cleanup()

    def revision(self) -> str:
        with self.engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()

    def assert_matches_models(self) -> None:
        with self.engine.connect() as connection:
            diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
        self.assertEqual(diff, [])

    def test_fresh_database_is_built_to_match_the_models(self) -> None:
        migrate(self.engine)
        self.assertEqual(self.revision(), HEAD_REVISION)
        self.assert_matches_models()

    def test_known_games_receive_compatibility_modes(self) -> None:
        migrate(self.engine, "0006")
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO works (id,title,author,category,emoji,art,collection,position,"
                "artifact_hash,status,created_at) VALUES "
                "(12,'今日咖啡心情','A','c','x','art-one','feed',0,'other','live',CURRENT_TIMESTAMP),"
                "(14,'tetris','A','c','x','art-one','feed',0,'other-2','live',CURRENT_TIMESTAMP),"
                "(20,'native','A','c','x','art-one','feed',0,'native','live',CURRENT_TIMESTAMP)"
            ))
        migrate(self.engine)
        with self.engine.connect() as connection:
            modes = dict(connection.execute(text("SELECT id, viewport_mode FROM works")).all())
        self.assertEqual(modes, {12: "scroll", 14: "compress", 20: "fixed"})

    def test_pre_alembic_database_keeps_its_rows(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(LEGACY_WORKS))
            for column in ("artifact_hash", "category", "collection"):
                connection.execute(text(f"CREATE INDEX ix_works_{column} ON works ({column})"))
            connection.execute(
                text(
                    "INSERT INTO works VALUES (12, 'Coffee', 'MOOD CAFÉ', 'relax', '☕',"
                    " 'art-one', '0', '0', 'feed', 0, 'af359667cf6a8038')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO works VALUES (1, 'Jungle Escape', 'Mia', 'relax', '🌿',"
                    " 'art-one', '4.9K', '1.2K', 'discover', 0, NULL)"
                )
            )

        migrate(self.engine)

        self.assertEqual(self.revision(), HEAD_REVISION)
        self.assert_matches_models()
        with self.engine.connect() as connection:
            rows = connection.execute(text("SELECT artifact_hash, status FROM works")).all()
            work_columns = {column["name"] for column in inspect(connection).get_columns("works")}
            social_rows = {
                table: connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                for table in ("work_likes", "work_saves", "work_views", "work_shares")
            }
        # The fake discover card is gone; the real game is live.
        self.assertEqual(rows, [("af359667cf6a8038", "live")])
        self.assertTrue({"views", "likes"}.isdisjoint(work_columns))
        self.assertEqual(social_rows, {table: 0 for table in social_rows})

    def test_claiming_era_database_without_alembic_is_adopted(self) -> None:
        # Databases from the claiming branch have users but no alembic_version.
        migrate(self.engine, target="0002")
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE alembic_version"))

        migrate(self.engine)
        self.assertEqual(self.revision(), HEAD_REVISION)

    def test_database_already_at_0004_gains_the_work_indexes_and_keeps_its_likes(self) -> None:
        # Production ran 0004 before the likes/saves work_id indexes existed.
        migrate(self.engine, target="0004")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO works (id, title, author, category, emoji, art,"
                    " collection, position, artifact_hash, status, created_at)"
                    " VALUES (1, 'Coffee', 'MOOD', 'relax', '☕', 'art', 'feed', 0,"
                    " 'af359667cf6a8038', 'live', '2026-09-23 00:00:00')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO users (id, slug, name, handle, bio, avatar_fill,"
                    " level, xp, xp_goal, position, claimable)"
                    " VALUES (1, 'bee-1', 'Bee', '@bee', '', '#000', 1, 0, 10, 0, 1)"
                )
            )
            connection.execute(
                text("INSERT INTO work_likes VALUES (1, 1, '2026-09-23 00:00:00')")
            )

        migrate(self.engine)

        self.assertEqual(self.revision(), HEAD_REVISION)
        self.assert_matches_models()
        indexes = {
            table: {index["name"] for index in inspect(self.engine).get_indexes(table)}
            for table in ("work_likes", "work_saves")
        }
        self.assertIn("ix_work_likes_work_id", indexes["work_likes"])
        self.assertIn("ix_work_saves_work_id", indexes["work_saves"])
        with self.engine.connect() as connection:
            likes = connection.execute(text("SELECT count(*) FROM work_likes")).scalar_one()
        self.assertEqual(likes, 1)

    def test_migrating_twice_is_a_no_op(self) -> None:
        migrate(self.engine)
        migrate(self.engine)
        self.assertIn("works", inspect(self.engine).get_table_names())


if __name__ == "__main__":
    unittest.main()
