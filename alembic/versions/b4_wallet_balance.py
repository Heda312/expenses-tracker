"""cache saldo dompet

Revision ID: b4_wallet_balance
Revises: b3_budget_alerts
Create Date: 2026-11-03 09:00:00.000000

Saldo dompet bersifat dinamis (dihitung dari transaksi). Kolom cache di sini
hanya menyimpan hasil hitung terakhir supaya pembacaan cepat.
"""

from alembic import op
import sqlalchemy as sa

revision = "b4_wallet_balance"
down_revision = "b3_budget_alerts"
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {col["name"] for col in inspector.get_columns("accounts")}

    with op.batch_alter_table("accounts", schema=None) as batch_op:
        if "cached_balance" not in columns:
            batch_op.add_column(
                sa.Column("cached_balance", sa.Integer(), nullable=False, server_default="0")
            )
        if "balance_updated_at" not in columns:
            batch_op.add_column(sa.Column("balance_updated_at", sa.DateTime(), nullable=True))


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    columns = {col["name"] for col in inspector.get_columns("accounts")}

    with op.batch_alter_table("accounts", schema=None) as batch_op:
        if "balance_updated_at" in columns:
            batch_op.drop_column("balance_updated_at")
        if "cached_balance" in columns:
            batch_op.drop_column("cached_balance")
