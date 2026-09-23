"""Store the compatibility mode for each game's fixed viewport.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "works",
        sa.Column("viewport_mode", sa.String(), nullable=False, server_default="fixed"),
    )
    # Known production artifacts. Title fallbacks cover the development clone
    # and older immutable copies of the two original games.
    op.execute(
        "UPDATE works SET viewport_mode = 'scroll' "
        "WHERE artifact_hash IN ('048a638dca574e9695fc680755a0ddf9', "
        "'56c6a4df92ce487c8f2836fea124e91e', 'af359667cf6a8038') "
        "OR title = '今日咖啡心情'"
    )
    op.execute(
        "UPDATE works SET viewport_mode = 'compress' "
        "WHERE artifact_hash IN ('3b342383bc554031aa385fffabb7fa2a', "
        "'b89b2f4e3d594ce8a8e7ab8c05874031') "
        "OR lower(title) IN ('tetris', 'block drop', 'index.html')"
    )


def downgrade() -> None:
    op.drop_column("works", "viewport_mode")
