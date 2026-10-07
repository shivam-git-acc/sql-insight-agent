import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]
MAX_ROWS = 200


def get_schema() -> str:
    """One line per table: table(col type, col type, ...)."""
    sql = """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """
    tables: dict[str, list[str]] = {}
    with psycopg.connect(DATABASE_URL) as conn:
        for table, col, dtype in conn.execute(sql):
            tables.setdefault(table, []).append(f"{col} {dtype}")
    return "\n".join(f"{t}({', '.join(cols)})" for t, cols in tables.items())


def run_query(sql: str) -> tuple[list[str], list[tuple]]:
    # TODO (Day 2): connect as a read-only role and validate the SQL first.
    with psycopg.connect(DATABASE_URL) as conn:
        cur = conn.execute(sql)
        columns = [d.name for d in cur.description]
        return columns, cur.fetchmany(MAX_ROWS)
