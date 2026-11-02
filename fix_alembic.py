import sqlite3

conn = sqlite3.connect('data/app.db')
cursor = conn.cursor()
cursor.execute("UPDATE alembic_version SET version_num = '70b1450876be'")
conn.commit()
print(f"Updated {cursor.rowcount} row(s)")
cursor.execute("SELECT version_num FROM alembic_version")
print(f"Current version: {cursor.fetchone()[0]}")
conn.close()
