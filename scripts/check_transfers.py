"""Cek transaksi transfer."""
from app.db import SessionLocal
from app.models import Transaction

db = SessionLocal()
try:
    txs = db.query(Transaction).filter(Transaction.kind == "transfer").all()
    print("Transfer transactions:")
    for t in txs[:10]:
        print(f"ID={t.id}, kind={t.kind}, account_id={t.account_id}, to_account_id={t.to_account_id}, amount={t.amount}")
finally:
    db.close()
