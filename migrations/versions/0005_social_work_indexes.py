"""Index likes and saves by work for the per-work counts on every feed render.

The (user_id, work_id) primary key cannot serve a lookup on work_id alone.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-23
"""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_work_likes_work_id", "work_likes", ["work_id"])
    op.create_index("ix_work_saves_work_id", "work_saves", ["work_id"])


def downgrade() -> None:
    op.drop_index("ix_work_saves_work_id", table_name="work_saves")
    op.drop_index("ix_work_likes_work_id", table_name="work_likes")
