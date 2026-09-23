from alembic import context

from app.models import Base

config = context.config


def run_migrations() -> None:
    # app.db.migrate() hands over an open connection; the CLI gets one from
    # the same engine, so both always target BEEPLAY_DB_PATH.
    connection = config.attributes.get("connection")
    if connection is None:
        from app.db import engine

        with engine.begin() as connection:
            _configure_and_run(connection)
    else:
        _configure_and_run(connection)


def _configure_and_run(connection) -> None:
    # render_as_batch: SQLite cannot ALTER most column properties, so Alembic
    # has to copy-and-swap the table instead.
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


run_migrations()
