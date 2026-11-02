"""Test delete all data."""

import sqlite3

conn = sqlite3.connect('data/app.db')
cursor = conn.cursor()

# Check current data
tables = ['transactions', 'budgets', 'accounts', 'merchants', 'audit_logs', 'user_sessions', 'users', 'login_attempts']

print("Data sebelum hapus:")
for table in tables:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    print(f"  {table}: {count} rows")

# Delete all data
print("\nMenghapus semua data...")
cursor.execute("PRAGMA foreign_keys = OFF")
for table in tables:
    cursor.execute(f"DELETE FROM {table}")
    print(f"  Deleted from {table}")
cursor.execute("PRAGMA foreign_keys = ON")
conn.commit()

print("\nData setelah hapus:")
for table in tables:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    print(f"  {table}: {count} rows")

conn.close()
print("\nDone!")
