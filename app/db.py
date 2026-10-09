import os

import psycopg
from dotenv import load_dotenv

from app import guard

load_dotenv()
DATABASE_URL = os.environ["DATABASE_URL"]
STATEMENT_TIMEOUT = "5s"


def get_schema() -> str:
    """One line per table: table(col type, col type, ...)."""
    sql = """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
    """
    tables: dict[str, list[str]] = {}
    with psycopg.connect(DATABASE_URL, connect_timeout=10) as conn:
        for table, col, dtype in conn.execute(sql):
            tables.setdefault(table, []).append(f"{col} {dtype}")
    return "\n".join(f"{t}({', '.join(cols)})" for t, cols in tables.items())


def run_query(sql: str) -> tuple[str, list[str], list[tuple]]:
    """Validate and run a model-written query. Returns (executed_sql, columns, rows).

    Raises guard.UnsafeQueryError if the query is rejected, or psycopg.Error
    if the database rejects it.
    """
    safe_sql = guard.validate(sql)
    with psycopg.connect(DATABASE_URL, connect_timeout=10) as conn:
        # Second layer: even if validation missed something, the transaction
        # cannot write, and a runaway query is cancelled.
        conn.read_only = True
        conn.execute(f"SET statement_timeout = '{STATEMENT_TIMEOUT}'")
        cur = conn.execute(safe_sql)
        columns = [d.name for d in cur.description]
        return safe_sql, columns, cur.fetchall()
