"""How a generated game is played: "touch", or "head" through the camera."""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("generations") as batch:
        batch.add_column(sa.Column("controls", sa.String(), nullable=False, server_default="touch"))


def downgrade():
    with op.batch_alter_table("generations") as batch:
        batch.drop_column("controls")
