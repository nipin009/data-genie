"""Unit tests: request classification (no guessing allowed)."""
from app.classifier import classify

TABLES = ["dg_orders", "dg_customers", "dg_products", "dg_categories",
          "dg_order_items", "dg_payments", "dg_product_reviews"]


def test_in_scope_revenue():
    c = classify("What was total revenue by category in 2024?", TABLES)
    assert c.label == "in_scope"


def test_short_clear_metric_question_is_not_needlessly_clarified():
    assert classify("Revenue by city", TABLES).label == "in_scope"


def test_ambiguous_recent_sales():
    c = classify("Show me recent sales", TABLES)
    assert c.label == "ambiguous" and len(c.questions) > 0


def test_ambiguous_top_customers():
    c = classify("Who are the top customers?", TABLES)
    assert c.label == "ambiguous"


def test_unsupported_delete():
    assert classify("Delete all cancelled orders", TABLES).label == "unsupported"


def test_unsupported_forecast():
    assert classify("Predict next quarter revenue", TABLES).label == "unsupported"


def test_unrelated_joke():
    assert classify("Tell me a joke about pirates", TABLES).label == "unrelated"


def test_greetings_and_product_questions_are_assistant_info():
    assert classify("hello", TABLES).label == "assistant_info"
    assert classify("What can Data Genie do?", TABLES).label == "assistant_info"
    assert classify("How does this app work?", TABLES).label == "assistant_info"


def test_unrelated_capital():
    assert classify("What is the capital of France?", TABLES).label == "unrelated"


def test_database_question_missing_from_schema():
    assert classify("What is the warehouse temperature?", TABLES).label == "not_in_schema"


def test_schema_metadata_requests_are_not_data_queries():
    assert classify("How many tables are there in the database?", TABLES).label == "schema_request"
    assert classify("Give the table anmes only", TABLES).label == "schema_request"
    assert classify("Give the schema of each table which you have", TABLES).label == "schema_request"


def test_direct_customer_identifiers_are_restricted():
    assert classify("Export customer email addresses", TABLES).label == "unsupported"
