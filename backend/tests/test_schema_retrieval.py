"""Unit tests: schema retrieval selects join-capable dg_ tables in local_db."""
from app.schema_introspection import extract_schema
from app.schema_retrieval import retrieve_relevant_schema


def _mem_snapshot():
    from sqlalchemy import create_engine as ce
    from sqlalchemy import text
    eng = ce("sqlite:///:memory:")
    with eng.begin() as c:
        c.execute(text("CREATE TABLE dg_customers (customer_id INTEGER PRIMARY KEY, country VARCHAR(20))"))
        c.execute(text("CREATE TABLE dg_orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES dg_customers(customer_id), total_amount FLOAT)"))
        c.execute(text("CREATE TABLE dg_products (product_id INTEGER PRIMARY KEY, product_name VARCHAR(50))"))
        c.execute(text("CREATE TABLE dg_order_items (order_item_id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES dg_orders(order_id), product_id INTEGER REFERENCES dg_products(product_id), quantity INTEGER)"))
    return extract_schema(eng)


def test_retrieval_includes_join_neighbors():
    snap = _mem_snapshot()
    assert "dg_orders" in snap.table_names()
    ret = retrieve_relevant_schema("total revenue by product", snap)
    assert "dg_order_items" in ret["selected"] or "dg_orders" in ret["selected"]
    assert len(ret["selected"]) >= 2


def test_retrieval_customers_orders():
    snap = _mem_snapshot()
    ret = retrieve_relevant_schema("top customers by spend and country", snap)
    assert "dg_customers" in ret["selected"]
