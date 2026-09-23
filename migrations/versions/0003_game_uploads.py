"""Game uploads: status, audit trail, health reports, failed uploads.

Also deletes the prototype's fake discover and profile cards: from here on
every work is a real, playable upload.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-23
"""
from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("claimable", sa.Boolean(), nullable=False, server_default=sa.true())
        )

    op.execute("DELETE FROM works WHERE collection IN ('discover', 'profile')")

    with op.batch_alter_table("works") as batch:
        batch.add_column(
            sa.Column("status", sa.String(), nullable=False, server_default="live")
        )
        batch.add_column(sa.Column("description", sa.String(), nullable=True))
        batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_works_status", ["status"])
    # SQLite cannot add a column with a non-constant default, so backfill and
    # then tighten it in a second copy-and-swap.
    op.execute("UPDATE works SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL")
    with op.batch_alter_table("works") as batch:
        batch.alter_column("created_at", existing_type=sa.DateTime(), nullable=False)

    op.create_table(
        "work_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("work_id", sa.Integer(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("actor", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("before", sa.Text(), nullable=True),
        sa.Column("after", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_work_events_work_id", "work_events", ["work_id"])

    op.create_table(
        "health_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("work_id", sa.Integer(), sa.ForeignKey("works.id"), nullable=False),
        sa.Column("artifact_hash", sa.String(), nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_health_events_work_id", "health_events", ["work_id"])
    op.create_index("ix_health_events_session_id", "health_events", ["session_id"])
    op.create_index("ix_health_events_at", "health_events", ["at"])

    op.create_table(
        "failed_uploads",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("category", sa.String(), nullable=False),
        sa.Column("emoji", sa.String(), nullable=False),
        sa.Column("art", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("error", sa.String(), nullable=False),
        sa.Column("stored_path", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_work_id", sa.Integer(), sa.ForeignKey("works.id"), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("failed_uploads")
    op.drop_table("health_events")
    op.drop_table("work_events")
    with op.batch_alter_table("works") as batch:
        batch.drop_index("ix_works_status")
        batch.drop_column("created_at")
        batch.drop_column("description")
        batch.drop_column("status")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("claimable")
