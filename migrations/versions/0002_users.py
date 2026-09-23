"""Claimable tester identities, and works.user_id.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("handle", sa.String(), nullable=False),
        sa.Column("bio", sa.String(), nullable=False),
        sa.Column("avatar_fill", sa.String(), nullable=False),
        sa.Column("saved_count", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("xp", sa.Integer(), nullable=False),
        sa.Column("xp_goal", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("claim_token", sa.String(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_slug", "users", ["slug"], unique=True)
    with op.batch_alter_table("works") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.create_index("ix_works_user_id", ["user_id"])
        batch.create_foreign_key("fk_works_user_id_users", "users", ["user_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("works") as batch:
        batch.drop_constraint("fk_works_user_id_users", type_="foreignkey")
        batch.drop_index("ix_works_user_id")
        batch.drop_column("user_id")
    op.drop_index("ix_users_slug", table_name="users")
    op.drop_table("users")
