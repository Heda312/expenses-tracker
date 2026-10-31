"""replace user email with username"""
from alembic import op
import sqlalchemy as sa

revision = "b1_username_auth"
down_revision = "70b1450876be"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.alter_column("email", new_column_name="username", existing_type=sa.String(190))


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.alter_column("username", new_column_name="email", existing_type=sa.String(80))
