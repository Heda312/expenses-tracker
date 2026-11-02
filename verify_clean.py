"""Verify delete account cleans all data except categories."""

import sqlite3

conn = sqlite3.connect('data/app.db')
cursor = conn.cursor()

print("=== Current Data State ===\n")

# Show categories (should remain)
cursor.execute("SELECT id, name, kind FROM categories ORDER BY sort_order")
categories = cursor.fetchall()
print(f"Categories ({len(categories)} rows):")
for cat in categories[:5]:  # Show first 5
    print(f"  {cat[0]}: {cat[1]} ({cat[2]})")
if len(categories) > 5:
    print(f"  ... and {len(categories) - 5} more")

print("\n=== Transaction Data (should be 0) ===")
tables = ['transactions', 'budgets', 'accounts', 'merchants', 'audit_logs', 'user_sessions', 'users', 'login_attempts']

for table in tables:
    cursor.execute(f"SELECT COUNT(*) FROM {table}")
    count = cursor.fetchone()[0]
    status = "OK" if count == 0 else "NOT EMPTY"
    print(f"  {table}: {count} rows - {status}")

# Check if any transactions with status != 'confirmed'
cursor.execute("SELECT COUNT(*) FROM transactions WHERE status != 'confirmed'")
pending = cursor.fetchone()[0]
if pending > 0:
    print(f"\n⚠️  Found {pending} non-confirmed transactions")

conn.close()
