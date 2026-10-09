from contextlib import contextmanager

from sqlalchemy import create_engine, text

from app.entity_resolution import bind_planned_filters, resolve_entities
from app.query_planning import PlannedFilter, StructuredQueryPlan, build_planned_query_spec
from app.query_spec import FilterSpec, QuerySpec, build_query_spec
from app.schema_introspection import ColumnInfo, SchemaSnapshot, TableInfo
from app.semantic_validation import validate_semantics


def test_last_month_becomes_an_exact_server_side_date_range():
    spec = build_query_spec("Sales last month")
    date_filter = next(item for item in spec.filters if item.source == "date_resolver")
    assert date_filter.table == "dg_orders"
    assert date_filter.column == "order_date"
    assert date_filter.operator == "between"
    assert date_filter.value < date_filter.end_value


def test_entity_resolver_binds_a_live_category_value(monkeypatch):
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE dg_categories (category_id INTEGER, category_name TEXT)"))
        conn.execute(text("INSERT INTO dg_categories VALUES (1, 'Books'), (2, 'Electronics')"))

    @contextmanager
    def sqlite_session():
        with engine.connect() as conn:
            yield conn

    monkeypatch.setattr("app.entity_resolution.readonly_session", sqlite_session)
    snapshot = SchemaSnapshot(
        tables={"dg_categories": TableInfo(
            name="dg_categories",
            columns=[ColumnInfo("category_id", "INTEGER", False, is_pk=True),
                     ColumnInfo("category_name", "TEXT", False)],
            primary_keys=["category_id"],
        )},
        join_edges=[],
    )
    resolution = resolve_entities("Show sales of Books", snapshot, ["dg_categories"])
    assert [(item.table, item.column, item.value) for item in resolution.filters] == [
        ("dg_categories", "category_name", "Books")
    ]


def test_semantic_validator_rejects_sql_that_drops_a_resolved_value_or_date():
    spec = QuerySpec(filters=[
        FilterSpec("dg_categories.category_name", "equals", "Books", table="dg_categories", column="category_name", source="entity_resolution"),
        FilterSpec("order_date", "between", "2026-09-01", table="dg_orders", column="order_date",
                   end_value="2026-10-01", source="date_resolver"),
    ])
    correct = """SELECT SUM(oi.unit_price) AS revenue FROM dg_orders o
    JOIN dg_order_items oi ON oi.order_id = o.order_id
    JOIN dg_products p ON p.product_id = oi.product_id
    JOIN dg_categories c ON c.category_id = p.category_id
    WHERE c.category_name = 'Books' AND o.order_date >= '2026-09-01'
      AND o.order_date < '2026-10-01' LIMIT 100"""
    omitted = """SELECT SUM(oi.unit_price) AS revenue FROM dg_orders o
    JOIN dg_order_items oi ON oi.order_id = o.order_id
    JOIN dg_products p ON p.product_id = oi.product_id
    JOIN dg_categories c ON c.category_id = p.category_id LIMIT 100"""
    assert validate_semantics(correct, spec) is None
    error = validate_semantics(omitted, spec)
    assert error and "resolved filter value 'Books' is missing" in error


def test_planned_business_filter_binds_to_a_safe_schema_column():
    snapshot = SchemaSnapshot(
        tables={"dg_categories": TableInfo(
            name="dg_categories",
            columns=[ColumnInfo("category_id", "INTEGER", False, is_pk=True),
                     ColumnInfo("category_name", "TEXT", False)],
            primary_keys=["category_id"],
        )},
        join_edges=[],
    )
    planned = FilterSpec("category", "equals", "Books", source="structured_plan")
    bind_planned_filters([planned], snapshot, ["dg_categories"])
    assert (planned.table, planned.column, planned.field, planned.source) == (
        "dg_categories", "category_name", "dg_categories.category_name", "planned_field_binding"
    )


def test_structured_plan_preserves_a_natural_language_filter_for_validation():
    plan = StructuredQueryPlan(
        metrics=["total_revenue"], dimensions=["category"],
        filters=[PlannedFilter(field="category", operator="equals", value="Books")],
    )
    spec = build_planned_query_spec("What were sales of Books?", plan)
    assert "total_revenue" in spec.metrics
    assert "category" in spec.dimensions
    assert any(item.field == "category" and item.value == "Books" for item in spec.filters)
