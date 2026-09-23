"""Baseline: the works table as first deployed.

Revision ID: 0001
Revises:
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "works",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("author", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("emoji", sa.String(), nullable=False),
        sa.Column("art", sa.String(), nullable=False),
        sa.Column("views", sa.String(), nullable=False),
        sa.Column("likes", sa.String(), nullable=False),
        sa.Column("collection", sa.String(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("artifact_hash", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_works_artifact_hash", "works", ["artifact_hash"])
    op.create_index("ix_works_category", "works", ["category"])
    op.create_index("ix_works_collection", "works", ["collection"])


def downgrade() -> None:
    op.drop_table("works")
