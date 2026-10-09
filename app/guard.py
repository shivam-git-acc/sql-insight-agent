"""Validation of model-generated SQL before it reaches the database.

The model's output is treated as untrusted input. A query is allowed only if it
parses as exactly one read-only query that touches application tables and calls
no dangerous functions. A row limit is then enforced on the result.

This is one layer of three; the others are a read-only transaction with a
statement timeout (app/db.py) and a least-privilege database role
(sql/readonly_role.sql).
"""

import sqlglot
from sqlglot import exp

MAX_ROWS = 200

# Statement types that change data, schema, permissions or session state.
FORBIDDEN_NODES = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.TruncateTable,
    exp.Grant,
    exp.Command,  # anything sqlglot cannot model, e.g. COPY, VACUUM, SET
    exp.Into,  # SELECT ... INTO new_table
    exp.Lock,  # SELECT ... FOR UPDATE
)

# Postgres functions that read files, sleep, change settings or reach other servers.
FORBIDDEN_FUNCTIONS = {
    "pg_sleep",
    "pg_read_file",
    "pg_read_binary_file",
    "pg_ls_dir",
    "pg_stat_file",
    "pg_terminate_backend",
    "pg_cancel_backend",
    "set_config",
    "current_setting",
    "lo_import",
    "lo_export",
    "dblink",
    "dblink_exec",
    "query_to_xml",
}

FORBIDDEN_SCHEMAS = {"pg_catalog", "information_schema"}


class UnsafeQueryError(ValueError):
    """Raised when a query is rejected; the message says why."""


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    return node.sql_name().lower()


def validate(sql: str) -> str:
    """Return a safe, row-limited version of `sql`, or raise UnsafeQueryError."""
    try:
        statements = [s for s in sqlglot.parse(sql, read="postgres") if s is not None]
    except sqlglot.errors.ParseError as exc:
        raise UnsafeQueryError("query could not be parsed") from exc

    if len(statements) != 1:
        raise UnsafeQueryError("exactly one statement is allowed")
    tree = statements[0]

    if not isinstance(tree, exp.Query):
        raise UnsafeQueryError("only SELECT queries are allowed")

    found = tree.find(*FORBIDDEN_NODES)
    if found is not None:
        raise UnsafeQueryError(f"{found.key.upper()} is not allowed")

    for func in tree.find_all(exp.Func):
        name = _function_name(func)
        if name in FORBIDDEN_FUNCTIONS or name.startswith("pg_"):
            raise UnsafeQueryError(f"function {name} is not allowed")

    for table in tree.find_all(exp.Table):
        schema = table.db.lower()
        name = table.name.lower()
        if schema in FORBIDDEN_SCHEMAS or name.startswith("pg_"):
            raise UnsafeQueryError(f"system table {name} is not allowed")

    return _enforce_limit(tree).sql(dialect="postgres")


def _enforce_limit(tree: exp.Query) -> exp.Query:
    limit = tree.args.get("limit")
    current = None
    if isinstance(limit, exp.Limit):
        value = limit.expression
        if isinstance(value, exp.Literal) and value.is_int:
            current = int(value.this)
    if current is None or current > MAX_ROWS:
        tree = tree.limit(MAX_ROWS)
    return tree
