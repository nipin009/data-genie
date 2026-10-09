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


def test_extended_schema_concepts_are_not_rejected_as_missing():
    assert classify("Campaign conversion rate by campaign", TABLES).label == "in_scope"
    assert classify("Give me supplier performance", TABLES).label == "ambiguous"


def test_schema_metadata_requests_are_not_data_queries():
    assert classify("How many tables are there in the database?", TABLES).label == "schema_request"
    assert classify("Give the table anmes only", TABLES).label == "schema_request"
    assert classify("Give the schema of each table which you have", TABLES).label == "schema_request"
    assert classify("Give all the tables in my db", TABLES).label == "schema_request"
    assert classify("Name al the tables in my db", TABLES).label == "schema_request"
    assert classify("Name the column names in dg_vendors", TABLES).label == "schema_request"
    assert classify("Which table has money related data", TABLES).label == "schema_request"
    # Word order and an unrelated misspelling must not send a metadata lookup
    # into the SQL-generation path.
    assert classify("which have moeny stats which table", TABLES).label == "schema_request"
    assert classify("where do I find the tables for financial values", TABLES).label == "schema_request"


def test_user_is_customer_domain_term():
    assert classify("Name all users whose name starts with A", TABLES).label == "in_scope"


def test_direct_customer_identifiers_are_restricted():
    assert classify("Export customer email addresses", TABLES).label == "unsupported"


def test_variants_of_writes_and_contact_data_are_blocked():
    assert classify("Change all cancelled orders to delivered", TABLES).label == "unsupported"
    assert classify("Download every customer's email address and mobile number", TABLES).label == "unsupported"


def test_vague_performer_request_requires_a_metric():
    result = classify("Show me our strongest performers", TABLES)
    assert result.label == "ambiguous"
    assert "metric" in result.missing


def test_structured_llm_metadata_route_is_not_vetoed_by_regex(monkeypatch):
    from app.classifier import Classification
    monkeypatch.setattr("app.classifier._classify_with_llm", lambda *_: Classification(
        "schema_request", "model recognized a non-canonical schema question"
    ))
    assert classify("Where is revenue stored?", TABLES).label == "schema_request"
