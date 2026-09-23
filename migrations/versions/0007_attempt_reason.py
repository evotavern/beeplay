"""Why the provider refused a generation attempt."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("generation_attempts") as batch:
        batch.add_column(sa.Column("reason", sa.String()))


def downgrade():
    with op.batch_alter_table("generation_attempts") as batch:
        batch.drop_column("reason")
