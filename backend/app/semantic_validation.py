"""Checks whether generated SQL covers the structured user requirements.

This is intentionally conservative: uncertain SQL is repaired or declined,
rather than silently executing a plausible but wrong query.
"""
import re
from typing import List, Optional

from .query_spec import QuerySpec


def validate_semantics(sql: str, spec: Optional[QuerySpec]) -> Optional[str]:
    if not spec:
        return None
    low = (sql or "").lower()
    errors: List[str] = []
    table_for_output = {
        "customer_name": "dg_customers", "product_name": "dg_products",
        "payment_status": "dg_payments", "country": "dg_customers",
    }
    for output in spec.required_outputs:
        table = table_for_output.get(output)
        if table and table not in low:
            errors.append(f"requested output '{output}' is missing its required table")

    for metric in spec.metrics:
        if metric in ("total_revenue", "lifetime_spend") and not ("sum(" in low and ("line_total" in low or "unit_price" in low or "total_amount" in low)):
            errors.append("requested revenue/spend metric is not calculated")
        elif metric == "avg_rating" and not ("avg(" in low and "rating" in low and "dg_product_reviews" in low):
            errors.append("requested average rating metric is not calculated from reviews")
        elif metric == "return_rate" and not ("returned_quantity" in low and "nullif" in low):
            errors.append("requested return rate metric is not calculated")
        elif metric == "avg_order_value" and not ("avg(" in low and "total_amount" in low):
            errors.append("requested average order value metric is not calculated")

    if "category" in spec.dimensions and not ("dg_categories" in low and "group by" in low):
        errors.append("requested category grouping is missing")
    if "month" in spec.dimensions and not ("group by" in low and any(x in low for x in ("date_trunc", "to_char", "strftime"))):
        errors.append("requested monthly grouping is missing")

    for f in spec.filters:
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

    if spec.top_n and not re.search(rf"\blimit\s+{spec.top_n}\b", low):
        errors.append(f"requested Top {spec.top_n} limit is missing")
    if spec.sort_direction == "desc" and "order by" not in low:
        errors.append("requested descending ranking is missing")
    return "; ".join(errors) if errors else None
