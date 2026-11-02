from sqlalchemy import inspect
from app.db import engine
from app.models import Base

insp = inspect(engine)
existing_tables = set(insp.get_table_names())
print("TABLES IN DB:", sorted(existing_tables))
print()
for table in Base.metadata.sorted_tables:
    if table.name not in existing_tables:
        print(f"MISSING TABLE: {table.name}")
        continue
    db_cols = {c["name"] for c in insp.get_columns(table.name)}
    model_cols = {c.name for c in table.columns}
    missing = model_cols - db_cols
    extra = db_cols - model_cols
    if missing or extra:
        print(f"{table.name}: missing={sorted(missing)} extra={sorted(extra)}")
