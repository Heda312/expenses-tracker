"""add budget alert columns

Revision ID: b3_budget_alerts
Revises: b2_username
Create Date: 2026-11-02 15:10:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b3_budget_alerts'
down_revision = 'b2_username'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {col['name'] for col in inspector.get_columns('budgets')}

    with op.batch_alter_table('budgets', schema=None) as batch_op:
        if 'alert_70_sent' not in columns:
            batch_op.add_column(sa.Column('alert_70_sent', sa.Boolean(), nullable=False, server_default=sa.false()))
        if 'alert_90_sent' not in columns:
            batch_op.add_column(sa.Column('alert_90_sent', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {col['name'] for col in inspector.get_columns('budgets')}

    with op.batch_alter_table('budgets', schema=None) as batch_op:
        if 'alert_70_sent' in columns:
            batch_op.drop_column('alert_70_sent')
        if 'alert_90_sent' in columns:
            batch_op.drop_column('alert_90_sent')
