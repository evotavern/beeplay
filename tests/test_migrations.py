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

        migrate(self.engine)

        self.assertEqual(self.revision(), HEAD_REVISION)
        self.assert_matches_models()
        with self.engine.connect() as connection:
            hashes = connection.execute(text("SELECT artifact_hash FROM works")).scalars().all()
        self.assertEqual(hashes, ["af359667cf6a8038"])

    def test_claiming_era_database_without_alembic_is_adopted(self) -> None:
        # Databases from the claiming branch have users but no alembic_version.
        migrate(self.engine, target="0002")
        with self.engine.begin() as connection:
            connection.execute(text("DROP TABLE alembic_version"))

        migrate(self.engine)
        self.assertEqual(self.revision(), HEAD_REVISION)

    def test_migrating_twice_is_a_no_op(self) -> None:
        migrate(self.engine)
        migrate(self.engine)
        self.assertIn("works", inspect(self.engine).get_table_names())


if __name__ == "__main__":
    unittest.main()
