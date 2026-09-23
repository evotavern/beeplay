"""Real social interactions, with all counters starting from zero.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # These columns contained prototype display strings, not measurements.
    # Dropping them deliberately resets social state without touching users,
    # uploaded games, health signals, or the operational audit trail.
    with op.batch_alter_table("works") as batch:
        batch.drop_column("views")
        batch.drop_column("likes")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("saved_count")

    op.create_table(
        "work_likes",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("work_id", sa.Integer(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "work_id"),
    )
    op.create_index("ix_work_likes_work_id", "work_likes", ["work_id"])
    op.create_table(
        "work_saves",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("work_id", sa.Integer(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", "work_id"),
    )
    op.create_index("ix_work_saves_work_id", "work_saves", ["work_id"])
    op.create_table(
        "work_views",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("work_id", sa.Integer(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("work_id", "session_id"),
    )
    op.create_index("ix_work_views_work_id", "work_views", ["work_id"])
    op.create_index("ix_work_views_user_id", "work_views", ["user_id"])
    op.create_index("ix_work_views_session_id", "work_views", ["session_id"])
    op.create_index("ix_work_views_created_at", "work_views", ["created_at"])
    op.create_table(
        "work_shares",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("work_id", sa.Integer(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("event_id", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_shares_work_id", "work_shares", ["work_id"])
    op.create_index("ix_work_shares_user_id", "work_shares", ["user_id"])
    op.create_index("ix_work_shares_event_id", "work_shares", ["event_id"], unique=True)
    op.create_index("ix_work_shares_created_at", "work_shares", ["created_at"])


def downgrade() -> None:
    op.drop_table("work_shares")
    op.drop_table("work_views")
    op.drop_table("work_saves")
    op.drop_table("work_likes")
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("saved_count", sa.Integer(), nullable=False, server_default="0")
        )
    with op.batch_alter_table("works") as batch:
        batch.add_column(sa.Column("likes", sa.String(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("views", sa.String(), nullable=False, server_default="0"))
