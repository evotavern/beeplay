"""Real accounts replace the eight claimable tester identities.

Every claimable user that exists at this point is one of the seeded bees,
whose history is a mix of many strangers. Their works and failed uploads
move to the house account; their likes, saves and unpublished drafts are
dropped; views and shares keep counting but belong to nobody. The audit
trail in work_events is left as it was.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

HOUSE_SLUG = "beeplay"
HOUSE_NAME = "蜂玩 BeePlay"


def _retire_bees(connection) -> None:
    bees = [row[0] for row in connection.execute(sa.text("SELECT id FROM users WHERE claimable"))]
    if not bees:
        return
    house = connection.execute(
        sa.text("SELECT id FROM users WHERE slug = :slug"), {"slug": HOUSE_SLUG}
    ).scalar()
    if house is None:
        connection.execute(
            sa.text(
                "INSERT INTO users (slug, name, handle, bio, avatar_fill, level, xp, xp_goal,"
                " position, claimable) VALUES (:slug, :name, '@beeplay', '蜂玩团队的官方作品。',"
                " 'c8f05a', 1, 0, 1000, 99, 0)"
            ),
            {"slug": HOUSE_SLUG, "name": HOUSE_NAME},
        )
        house = connection.execute(
            sa.text("SELECT id FROM users WHERE slug = :slug"), {"slug": HOUSE_SLUG}
        ).scalar()

    ids = sa.bindparam("ids", expanding=True)
    params = {"ids": bees, "house": house, "name": HOUSE_NAME}

    def run(sql: str) -> None:
        connection.execute(sa.text(sql).bindparams(ids), params)

    run("UPDATE works SET user_id = :house, author = :name WHERE user_id IN :ids")
    run("UPDATE failed_uploads SET user_id = :house WHERE user_id IN :ids")
    run("DELETE FROM work_likes WHERE user_id IN :ids")
    run("DELETE FROM work_saves WHERE user_id IN :ids")
    run("UPDATE work_views SET user_id = NULL WHERE user_id IN :ids")
    run("UPDATE work_shares SET user_id = NULL WHERE user_id IN :ids")
    # A published generation is the telemetry of a live game: keep it with
    # the game. Everything else was a draft, possibly mid-run.
    run("UPDATE generations SET user_id = :house WHERE user_id IN :ids AND work_id IS NOT NULL")
    drafts = "SELECT id FROM generations WHERE user_id IN :ids"
    run(f"DELETE FROM generation_events WHERE generation_id IN ({drafts})")
    run(f"DELETE FROM generation_attempts WHERE generation_id IN ({drafts})")
    run("DELETE FROM generations WHERE user_id IN :ids")
    run("DELETE FROM users WHERE id IN :ids")


def upgrade() -> None:
    _retire_bees(op.get_bind())

    with op.batch_alter_table("generations") as batch:
        batch.drop_column("claim_hash")

    with op.batch_alter_table("users") as batch:
        batch.drop_column("handle")
        batch.drop_column("position")
        batch.drop_column("claim_token")
        batch.drop_column("last_seen_at")
        batch.alter_column("claimable", new_column_name="loginable")
        batch.add_column(sa.Column("handle_locked", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("avatar_path", sa.String(), nullable=True))
        batch.add_column(sa.Column("password_hash", sa.String(), nullable=True))
        batch.add_column(sa.Column("reset_token_hash", sa.String(), nullable=True))
        batch.add_column(sa.Column("reset_expires_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("profile_prompted", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.current_timestamp())
        )
        batch.alter_column("bio", server_default="")
        batch.alter_column("level", server_default="1")
        batch.alter_column("xp", server_default="0")
        batch.alter_column("xp_goal", server_default="1000")
        batch.create_index("ix_users_reset_token_hash", ["reset_token_hash"])

    # The house account was the one unclaimable identity; it stays unloginable.
    op.execute(sa.text("UPDATE users SET handle_locked = 1 WHERE NOT loginable"))

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])


def downgrade() -> None:
    # The bees' mixed history is deliberately gone; there is nothing to put back.
    raise NotImplementedError("0008 is one-way: restore the pre-release backup instead")
