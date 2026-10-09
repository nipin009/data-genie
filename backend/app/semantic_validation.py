"""Checks whether generated SQL covers the structured user requirements.

This is intentionally conservative: uncertain SQL is repaired or declined,
rather than silently executing a plausible but wrong query.
"""
import re
from typing import List, Optional

import sqlglot
import sqlglot.expressions as exp

from .query_spec import QuerySpec


def validate_semantics(sql: str, spec: Optional[QuerySpec]) -> Optional[str]:
    if not spec:
        return None
    low = (sql or "").lower()
    errors: List[str] = []
    try:
        parsed = sqlglot.parse_one(sql, read="postgres")
        sql_tables = {table.name.lower() for table in parsed.find_all(exp.Table)}
        sql_columns = {column.name.lower() for column in parsed.find_all(exp.Column)}
        sql_literals = {
            str(literal.this).lower()
            for literal in parsed.find_all(exp.Literal)
            if literal.this is not None
        }
    except Exception:
        # Syntax validation will return the authoritative parse error.  Keep
        # this layer focused on requirements rather than masking it.
        parsed = None
        sql_tables, sql_columns, sql_literals = set(), set(), set()
    table_for_output = {
        "customer_name": "dg_customers", "product_name": "dg_products",
        "payment_status": "dg_payments", "country": "dg_customers",
        "product_review_status": "dg_product_reviews",
    }
    for output in spec.required_outputs:
        table = table_for_output.get(output)
        if table and table not in low:
            errors.append(f"requested output '{output}' is missing its required table")

    for metric in spec.metrics:
        if metric in ("total_revenue", "lifetime_spend") and not ("sum(" in low and ("line_total" in low or "unit_price" in low or "total_amount" in low)):
            errors.append("requested revenue/spend metric is not calculated")
        elif metric == "net_revenue_after_returns" and not ("sum(" in low and "returned_quantity" in low and ("unit_price" in low or "line_total" in low)):
            errors.append("requested net revenue after returns is not calculated")
        elif metric == "avg_rating" and not ("avg(" in low and "rating" in low and "dg_product_reviews" in low):
            errors.append("requested average rating metric is not calculated from reviews")
        elif metric == "products_without_reviews" and not ("dg_product_reviews" in low and ("left join" in low or "not exists" in low)):
            errors.append("requested products-without-reviews logic is missing")
        elif metric == "return_rate" and not ("returned_quantity" in low and "nullif" in low):
            errors.append("requested return rate metric is not calculated")
        elif metric == "avg_order_value" and not ("avg(" in low and "total_amount" in low):
            errors.append("requested average order value metric is not calculated")
        elif metric == "customer_signup_count" and not ("count(" in low and "signup_date" in low):
            errors.append("requested customer signup count is not calculated from signup dates")

    aggregate_requested = bool(spec.metrics)
    if "category" in spec.dimensions and not ("dg_categories" in low and "category_name" in low and (not aggregate_requested or "group by" in low)):
        errors.append("requested category grouping is missing")
    if "month" in spec.dimensions and not ("group by" in low and any(x in low for x in ("date_trunc", "to_char", "strftime"))):
        errors.append("requested monthly grouping is missing")

    for f in spec.filters:
        # Resolved filters must map to a real table/column and retain every
        # literal value in generated SQL.  This closes the common failure mode
        # where a model returns plausible total revenue while silently dropping
        # a value such as "Books" or a date range.
        if f.table and f.column:
            if f.table.lower() not in sql_tables:
                errors.append(f"resolved filter table '{f.table}' is missing")
            if f.column.lower() not in sql_columns:
                errors.append(f"resolved filter column '{f.column}' is missing")
            expected = [f.value] + ([f.end_value] if f.end_value is not None else [])
            for value in expected:
                if str(value).lower() not in sql_literals:
                    errors.append(f"resolved filter value '{value}' is missing")
            # The exact resolved requirement has already been checked; avoid
            # applying a broad legacy text check below.
            continue
        if f.operator == "year" and str(f.value) not in low:
            errors.append(f"requested year {f.value} filter is missing")
        elif f.operator == "last_days" and not ("interval" in low or "date('now'" in low):
            errors.append(f"requested last {f.value} days filter is missing")
        elif f.operator == "last_months" and not ("interval" in low or "date('now'" in low):
            errors.append(f"requested last {f.value} months filter is missing")
        elif f.operator == "equals" and str(f.value).lower() not in low:
            errors.append(f"requested {f.field}={f.value} filter is missing")
        elif f.operator == "contains" and str(f.value).lower() not in low:
            errors.append(f"requested product filter '{f.value}' is missing")
        elif f.operator == "current_month" and not ("start of month" in low or "date_trunc('month'" in low):
            errors.append("requested current-month filter is missing")
        elif f.operator == "last_year" and not ("current_date" in low or "date('now'" in low):
            errors.append("requested last-year filter must be relative to the current date")

    if spec.top_n and not re.search(rf"\blimit\s+{spec.top_n}\b", low):
        errors.append(f"requested Top {spec.top_n} limit is missing")
    if spec.sort_direction == "desc" and "order by" not in low:
        errors.append("requested descending ranking is missing")
    return "; ".join(errors) if errors else None
