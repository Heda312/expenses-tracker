import sqlite3

conn = sqlite3.connect('data/app.db')
cursor = conn.cursor()

# Check tables
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = cursor.fetchall()
print("Tables:", [t[0] for t in tables])

# Check users table schema
cursor.execute("PRAGMA table_info(users)")
cols = cursor.fetchall()
print("\nusers columns:")
for col in cols:
    print(f"  {col[1]} {col[2]}")

# Check budgets table schema
cursor.execute("PRAGMA table_info(budgets)")
cols = cursor.fetchall()
print("\nbudgets columns:")
for col in cols:
    print(f"  {col[1]} {col[2]}")

conn.close()
