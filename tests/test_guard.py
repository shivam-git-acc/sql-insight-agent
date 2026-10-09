import pytest

from app.guard import MAX_ROWS, UnsafeQueryError, validate

SAFE = [
    "SELECT * FROM customers",
    "SELECT c.company_name, COUNT(o.order_id) AS n FROM customers c "
    "JOIN orders o ON c.customer_id = o.customer_id GROUP BY c.company_name ORDER BY n DESC LIMIT 5",
    "WITH t AS (SELECT category_id, COUNT(*) AS n FROM products GROUP BY category_id) SELECT * FROM t",
    "SELECT country FROM customers UNION SELECT country FROM suppliers",
    "SELECT product_name FROM products WHERE unit_price > (SELECT AVG(unit_price) FROM products)",
    "SELECT EXTRACT(YEAR FROM order_date) AS y, COUNT(*) FROM orders GROUP BY y",
]

UNSAFE = [
    "DROP TABLE orders",
    "DELETE FROM orders",
    "DELETE FROM orders WHERE 1=1",
    "UPDATE products SET unit_price = 0",
    "INSERT INTO shippers (shipper_id, company_name) VALUES (99, 'x')",
    "TRUNCATE orders",
    "ALTER TABLE orders ADD COLUMN x INT",
    "CREATE TABLE stolen AS SELECT * FROM customers",
    "GRANT ALL ON orders TO PUBLIC",
    "SELECT 1; DROP TABLE orders",
    "SELECT * FROM customers; DELETE FROM customers",
    "WITH d AS (DELETE FROM orders RETURNING *) SELECT * FROM d",
    "SELECT * INTO backup_orders FROM orders",
    "SELECT * FROM orders FOR UPDATE",
    "SELECT pg_sleep(30)",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT set_config('statement_timeout', '0', false)",
    "SELECT current_setting('data_directory')",
    "SELECT * FROM pg_catalog.pg_user",
    "SELECT usename, passwd FROM pg_shadow",
    "SELECT * FROM information_schema.tables",
    "COPY customers TO '/tmp/out.csv'",
    "SET statement_timeout = 0",
    "this is not sql at all ((",
]


@pytest.mark.parametrize("sql", SAFE)
def test_safe_queries_pass(sql):
    validate(sql)


@pytest.mark.parametrize("sql", UNSAFE)
def test_unsafe_queries_rejected(sql):
    with pytest.raises(UnsafeQueryError):
        validate(sql)


def test_limit_added_when_missing():
    assert f"LIMIT {MAX_ROWS}" in validate("SELECT * FROM customers")


def test_large_limit_reduced():
    assert f"LIMIT {MAX_ROWS}" in validate("SELECT * FROM customers LIMIT 100000")


def test_small_limit_kept():
    out = validate("SELECT * FROM customers LIMIT 5")
    assert "LIMIT 5" in out
    assert f"LIMIT {MAX_ROWS}" not in out
