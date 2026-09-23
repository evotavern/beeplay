"""Persist the small social layer used by the eight demo identities.

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


def upgrade() -> None:
    op.create_table(
        "user_follows",
        sa.Column("follower_id", sa.Integer(), nullable=False),
        sa.Column("followed_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["follower_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["followed_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("follower_id", "followed_id"),
    )
    op.create_index("ix_user_follows_followed_id", "user_follows", ["followed_id"])
    op.create_table(
        "work_comments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("work_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["work_id"], ["works.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_comments_work_id", "work_comments", ["work_id"])
    op.create_index("ix_work_comments_user_id", "work_comments", ["user_id"])
    op.create_index("ix_work_comments_created_at", "work_comments", ["created_at"])
    op.create_table(
        "comment_likes",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("comment_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["comment_id"], ["work_comments.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "comment_id"),
    )
    op.create_index("ix_comment_likes_comment_id", "comment_likes", ["comment_id"])


def downgrade() -> None:
    op.drop_table("comment_likes")
    op.drop_table("work_comments")
    op.drop_table("user_follows")
