"""Regression tests for question-to-SQL semantic coverage and safety."""
from app.fallback_sql import build_fallback_sql
from app.query_spec import build_query_spec
from app.semantic_validation import validate_semantics
from app.sql_validation import validate_sql


KNOWN = {
    "dg_orders": {"order_id", "customer_id", "order_date", "status", "total_amount"},
    "dg_customers": {"customer_id", "first_name", "last_name", "country"},
    "dg_products": {"product_id", "product_name", "category_id"},
    "dg_order_items": {"order_id", "product_id", "quantity", "unit_price", "discount_pct", "returned_quantity"},
    "dg_payments": {"order_id", "status"},
    "dg_categories": {"category_id", "category_name"},
    "dg_product_reviews": {"product_id", "rating"},
}


def test_fallback_covers_detailed_order_request():
    q = "List orders with customer name, product names and payment status"
    sql = build_fallback_sql(q)
    assert validate_semantics(sql, build_query_spec(q)) is None
    assert validate_sql(sql, KNOWN).ok


def test_fallback_covers_date_and_rating_requirements():
    for q in (
        "Average product rating by category",
        "Orders with status pending placed in the last 30 days",
        "Show monthly revenue trend for the last 12 months",
        "Top 5 customers by lifetime spend with their country",
    ):
        assert validate_semantics(build_fallback_sql(q), build_query_spec(q)) is None, q


def test_fallback_covers_revenue_breakdown_by_country():
    sql = build_fallback_sql("Revenue by country in 2024")
    assert "c.country" in sql and "GROUP BY c.country" in sql
    assert "2024" in sql


def test_fallback_declines_an_unknown_breakdown_instead_of_returning_a_total():
    assert build_fallback_sql("Revenue by city") == ""


def test_fallback_preserves_specific_offline_requests():
    cases = {
        "How many customers signed up this month?": ("customer_count", "signup_date"),
        "List active products by category": ("dg_categories", "p.is_active"),
        "Top 5 products by revenue": ("limit 5", "product_name"),
        "Revenue excluding cancelled orders": ("status <> 'cancelled'",),
        "Return rate by product category": ("returned_quantity", "category_name"),
    }
    for question, fragments in cases.items():
        sql = build_fallback_sql(question).lower()
        assert all(fragment in sql for fragment in fragments), question
        assert validate_semantics(sql, build_query_spec(question)) is None, question


def test_net_revenue_after_returns_uses_the_canonical_returned_units_formula():
    question = "Total revenue by product category, net of returns"
    sql = build_fallback_sql(question).lower()
    assert "returned_quantity" in sql
    assert "net_revenue_after_returns" in sql
    assert validate_semantics(sql, build_query_spec(question)) is None
    from app.metrics import find_metrics
    assert [metric.name for metric in find_metrics(question)] == ["net_revenue_after_returns"]


def test_customer_listing_does_not_select_email():
    assert "email" not in build_fallback_sql("List customers").lower()


def test_semantic_validator_rejects_omitted_requirements():
    q = "Average product rating by category"
    wrong = "SELECT category_name, SUM(unit_price) FROM dg_categories GROUP BY category_name LIMIT 100"
    assert validate_semantics(wrong, build_query_spec(q))


def test_validator_allows_cte_and_blocks_file_functions():
    cte = "WITH x AS (SELECT order_id FROM dg_orders) SELECT order_id FROM x"
    assert validate_sql(cte, KNOWN).ok
    assert validate_sql("SELECT to_char(CURRENT_DATE, 'YYYY-MM')", KNOWN).ok
    assert not validate_sql("SELECT pg_read_file('/etc/passwd')", KNOWN).ok
