"""Unit tests: chart selection + grounded answers."""
from app.answer import grounded_answer
from app.visualization import choose_chart


def test_line_for_time_series():
    rows = [{"month": "2024-01", "revenue": 100.0}, {"month": "2024-02", "revenue": 120.0}]
    c = choose_chart(["month", "revenue"], rows, "monthly revenue trend")
    assert c["type"] == "line"


def test_bar_for_categories():
    rows = [{"category_name": "A", "revenue": 10}, {"category_name": "B", "revenue": 20}]
    assert choose_chart(["category_name", "revenue"], rows, "revenue by category")["type"] == "bar"


def test_table_for_many_rows():
    rows = [{"a": str(i), "v": i} for i in range(60)]
    assert choose_chart(["a", "v"], rows, "")["type"] == "table"


def test_empty_grounded():
    a = grounded_answer("revenue for X", ["revenue"], [])
    assert "no matching data" in a.lower()


def test_single_kpi_mentions_value():
    a = grounded_answer("total revenue?", ["total_revenue"], [{"total_revenue": 1234.5}])
    assert "1,234.50" in a


def test_numbers_come_from_rows():
    rows = [{"category_name": "Books", "revenue": 999}, {"category_name": "Toys", "revenue": 111}]
    a = grounded_answer("revenue by category?", ["category_name", "revenue"], rows)
    assert "Books" in a and "999" in a and "7788" not in a
