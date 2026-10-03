"""Unit tests: SQL validation guardrails (dg_-prefixed local_db tables)."""
from app.sql_validation import validate_sql

KNOWN = {
    "dg_orders": {"order_id", "customer_id", "order_date", "status", "total_amount"},
    "dg_customers": {"customer_id", "first_name", "country"},
}


def test_allows_simple_select_and_adds_limit():
    r = validate_sql("SELECT order_id, total_amount FROM dg_orders", KNOWN, 100)
    assert r.ok
    assert "LIMIT" in (r.fixed_sql or "").upper()


def test_rejects_insert():
    r = validate_sql("INSERT INTO dg_orders (order_id) VALUES (1)", KNOWN)
    assert not r.ok


def test_rejects_drop():
    assert not validate_sql("DROP TABLE dg_orders", KNOWN).ok


def test_rejects_multi_statement():
    assert not validate_sql("SELECT 1; SELECT 2", KNOWN).ok


def test_rejects_unknown_table():
    r = validate_sql("SELECT * FROM hackers", KNOWN)
    assert not r.ok and "Unknown table" in (r.error or "")


def test_rejects_unprefixed_table():
    # plain 'orders' must NOT resolve when local_db uses dg_orders
    r = validate_sql("SELECT order_id FROM orders", KNOWN)
    assert not r.ok


def test_rejects_unknown_column():
    r = validate_sql("SELECT ssn FROM dg_customers", KNOWN)
    assert not r.ok


def test_clamps_big_limit():
    r = validate_sql("SELECT order_id FROM dg_orders LIMIT 100000", KNOWN, 500)
    assert r.ok and "500" in (r.fixed_sql or "")


def test_rejects_pg_sleep():
    assert not validate_sql("SELECT pg_sleep(5)", KNOWN).ok


def test_allows_boolean_predicates_but_restricts_pii_columns():
    assert validate_sql("SELECT order_id FROM dg_orders WHERE status = 'pending' AND total_amount > 10", KNOWN).ok
    assert not validate_sql("SELECT email FROM dg_customers", KNOWN).ok
