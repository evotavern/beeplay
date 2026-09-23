"""One-shot generation jobs, provider attempts and playtest funnel."""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("generations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("claim_hash", sa.String(), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("details", sa.Text(), nullable=False),
        sa.Column("html", sa.Text()), sa.Column("error", sa.String()),
        sa.Column("timings", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime()), sa.Column("details_at", sa.DateTime()),
        sa.Column("playtest_at", sa.DateTime()),
        sa.Column("work_id", sa.Integer(), sa.ForeignKey("works.id")))
    op.create_index("ix_generations_user_id", "generations", ["user_id"])
    op.create_index("ix_generations_status", "generations", ["status"])
    op.create_table("generation_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generation_id", sa.String(), sa.ForeignKey("generations.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False), sa.Column("elapsed_ms", sa.Integer()),
        sa.Column("at", sa.DateTime(), nullable=False))
    op.create_index("ix_generation_events_generation_id", "generation_events", ["generation_id"])
    op.create_table("generation_keys",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("disabled", sa.Boolean(), nullable=False),
        sa.Column("cooldown_until", sa.DateTime()), sa.Column("last_used_at", sa.DateTime()))
    op.create_table("generation_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generation_id", sa.String(), sa.ForeignKey("generations.id"), nullable=False),
        sa.Column("key_id", sa.String(), nullable=False), sa.Column("model", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False), sa.Column("http_status", sa.Integer()),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("usage", sa.Text(), nullable=False), sa.Column("limits", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(), nullable=False))
    op.create_index("ix_generation_attempts_generation_id", "generation_attempts", ["generation_id"])


def downgrade():
    for table in ("generation_attempts", "generation_keys", "generation_events", "generations"):
        op.drop_table(table)
