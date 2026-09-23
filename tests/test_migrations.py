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

        # 0008 later drops the tester identities' likes; stop before it.
        migrate(self.engine, target="0007")

        indexes = {
            table: {index["name"] for index in inspect(self.engine).get_indexes(table)}
            for table in ("work_likes", "work_saves")
        }
        self.assertIn("ix_work_likes_work_id", indexes["work_likes"])
        self.assertIn("ix_work_saves_work_id", indexes["work_saves"])
        with self.engine.connect() as connection:
            likes = connection.execute(text("SELECT count(*) FROM work_likes")).scalar_one()
        self.assertEqual(likes, 1)

    def test_the_tester_identities_hand_their_games_to_the_house(self) -> None:
        migrate(self.engine, target="0007")
        rows = [
            "INSERT INTO users (id, slug, name, handle, bio, avatar_fill, level, xp, xp_goal,"
            " position, claimable) VALUES (1, 'beeplay', '蜂玩 BeePlay', '@beeplay', '', 'c8f05a',"
            " 1, 0, 1000, 8, 0), (2, 'bee-3', '阿尔法', '@alpha_lab', '', 'a8e6cf', 3, 180, 1500, 2, 1)",
            "INSERT INTO works (id, title, author, category, emoji, art, collection, position,"
            " artifact_hash, user_id, status, created_at) VALUES"
            " (1, 'Coffee', 'MOOD', 'relax', '☕', 'art-one', 'feed', 0, 'aaa', 1, 'live', '2026-09-23'),"
            " (2, 'Stones', '阿尔法', 'relax', '🪨', 'art-one', 'feed', 0, 'bbb', 2, 'live', '2026-09-23')",
            "INSERT INTO work_likes VALUES (2, 1, '2026-09-23')",
            "INSERT INTO work_saves VALUES (2, 1, '2026-09-23')",
            "INSERT INTO work_views (id, work_id, user_id, session_id, created_at)"
            " VALUES (1, 1, 2, 's1', '2026-09-23')",
            "INSERT INTO work_shares (id, work_id, user_id, event_id, created_at)"
            " VALUES (1, 1, 2, 'e1', '2026-09-23')",
            "INSERT INTO failed_uploads (id, user_id, title, category, emoji, art, error,"
            " stored_path, created_at) VALUES (1, 2, 'Broken', 'x', 'x', 'art-one', 'no index',"
            " '/tmp/1.zip', '2026-09-23')",
            "INSERT INTO generations (id, user_id, claim_hash, prompt, model, status, details, timings,"
            " created_at, work_id) VALUES"
            " ('published', 2, 'h', 'p', 'm', 'published', '{}', '{}', '2026-09-23', 2),"
            " ('draft', 2, 'h', 'p', 'm', 'generating', '{}', '{}', '2026-09-23', NULL)",
            "INSERT INTO generation_events (generation_id, kind, at) VALUES ('draft', 'submitted', '2026-09-23')",
            "INSERT INTO work_events (work_id, actor, kind, at) VALUES (2, 'user:bee-3', 'created', '2026-09-23')",
        ]
        with self.engine.begin() as connection:
            for row in rows:
                connection.execute(text(row))

        migrate(self.engine)

        self.assertEqual(self.revision(), HEAD_REVISION)
        self.assert_matches_models()
        with self.engine.connect() as connection:
            def one(sql):
                return connection.execute(text(sql)).all()

            self.assertEqual(one("SELECT slug, loginable, handle_locked FROM users"), [("beeplay", 0, 1)])
            self.assertEqual(one("SELECT id, user_id, author FROM works ORDER BY id"),
                             [(1, 1, "MOOD"), (2, 1, "蜂玩 BeePlay")])
            self.assertEqual(one("SELECT count(*) FROM work_likes") + one("SELECT count(*) FROM work_saves"),
                             [(0,), (0,)])
            self.assertEqual(one("SELECT user_id FROM work_views") + one("SELECT user_id FROM work_shares"),
                             [(None,), (None,)])
            self.assertEqual(one("SELECT user_id FROM failed_uploads"), [(1,)])
            self.assertEqual(one("SELECT id, user_id FROM generations"), [("published", 1)])
            self.assertEqual(one("SELECT count(*) FROM generation_events"), [(0,)])
            self.assertEqual(one("SELECT actor FROM work_events"), [("user:bee-3",)])

    def test_migrating_twice_is_a_no_op(self) -> None:
        migrate(self.engine)
        migrate(self.engine)
        self.assertIn("works", inspect(self.engine).get_table_names())


if __name__ == "__main__":
    unittest.main()
