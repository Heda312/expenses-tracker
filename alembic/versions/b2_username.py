"""use username instead of email

Revision ID: b2_username
Revises: 70b1450876be
Create Date: 2026-11-02 14:43:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b2_username'
down_revision = '70b1450876be'
branch_labels = None
depends_on = None


def upgrade():
    # Check if column exists first
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = [col['name'] for col in inspector.get_columns('users')]
    
    if 'email' in columns:
        with op.batch_alter_table('users', schema=None) as batch_op:
            batch_op.alter_column('email', new_column_name='username', existing_type=sa.String(190))
    elif 'username' not in columns:
        # Fresh install - no migration needed
        pass


def downgrade():
    with op.batch_alter_table('users', schema=None) as batch_op:
        batch_op.alter_column('username', new_column_name='email', existing_type=sa.String(80))
