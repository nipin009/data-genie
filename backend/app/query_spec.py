"""Structured, inspectable representation of a data question.

The application deliberately plans a question before it writes SQL.  The
heuristic parser covers the common retail analytics vocabulary offline; an LLM
may still use this object as a constrained planning contract for novel cases.
"""
from dataclasses import asdict, dataclass, field
import re
from typing import Any, Dict, List, Optional


@dataclass
class FilterSpec:
    field: str
    operator: str
    value: Any


@dataclass
class QuerySpec:
    metrics: List[str] = field(default_factory=list)
    dimensions: List[str] = field(default_factory=list)
    filters: List[FilterSpec] = field(default_factory=list)
    required_outputs: List[str] = field(default_factory=list)
    top_n: Optional[int] = None
    sort_direction: Optional[str] = None
    is_complex: bool = False

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def render(self) -> str:
        return (
            "QUERY REQUIREMENTS (do not omit any):\n"
            f"- metrics: {', '.join(self.metrics) or 'none explicitly named'}\n"
            f"- dimensions: {', '.join(self.dimensions) or 'none'}\n"
            f"- filters: {', '.join(f'{x.field} {x.operator} {x.value}' for x in self.filters) or 'none'}\n"
            f"- required outputs: {', '.join(self.required_outputs) or 'none'}\n"
            f"- top_n: {self.top_n or 'not requested'}; sort: {self.sort_direction or 'not specified'}"
        )


def build_query_spec(question: str) -> QuerySpec:
    q = (question or "").lower()
    spec = QuerySpec()
    is_net_revenue = any(x in q for x in ("net of returns", "net revenue", "revenue after returns"))
    if any(x in q for x in ("revenue", "sales", "gmv", "turnover")) and not is_net_revenue:
        spec.metrics.append("total_revenue")
    if is_net_revenue:
        spec.metrics.append("net_revenue_after_returns")
    if "lifetime spend" in q or ("customer" in q and "spend" in q):
        spec.metrics.append("lifetime_spend")
    if any(x in q for x in ("average product rating", "avg rating", "average rating", "stars")):
        spec.metrics.append("avg_rating")
    if "return rate" in q or "refund rate" in q:
        spec.metrics.append("return_rate")
    if "average order" in q or "aov" in q:
        spec.metrics.append("avg_order_value")
    if "order count" in q or "number of orders" in q or "how many orders" in q:
        spec.metrics.append("order_count")
    if ("how many customer" in q or "customer count" in q) and any(x in q for x in ("sign up", "signed up", "signup", "joined")):
        spec.metrics.append("customer_signup_count")

    dimension_terms = {
        "category": "category", "categor": "category", "country": "country",
        "customer segment": "customer_segment", "segment": "customer_segment",
        "month": "month", "monthly": "month", "week": "week", "quarter": "quarter",
        "product": "product", "customer": "customer",
    }
    for term, name in dimension_terms.items():
        if term in q and (f"by {term}" in q or term in ("monthly", "week", "quarter") or "trend" in q):
            if name not in spec.dimensions:
                spec.dimensions.append(name)

    year = re.search(r"\b(20\d{2})\b", q)
    if year and ("in " + year.group(1) in q or "year" in q):
        spec.filters.append(FilterSpec("order_date", "year", int(year.group(1))))
    days = re.search(r"last\s+(\d+)\s+days?", q)
    if days:
        spec.filters.append(FilterSpec("order_date", "last_days", int(days.group(1))))
    months = re.search(r"last\s+(\d+)\s+months?", q)
    if months:
        spec.filters.append(FilterSpec("order_date", "last_months", int(months.group(1))))
    if "last year" in q:
        spec.filters.append(FilterSpec("relative_date", "last_year", "current"))
    for status in ("pending", "processing", "shipped", "delivered", "cancelled", "returned"):
        if status in q:
            spec.filters.append(FilterSpec("order_status", "equals", status))
            break
    if "failed payment" in q or "failed payments" in q:
        spec.filters.append(FilterSpec("payment_status", "equals", "failed"))
    if "this month" in q and any(x in q for x in ("sign up", "signed up", "signup", "joined")):
        spec.filters.append(FilterSpec("signup_date", "current_month", "current"))
    quoted = re.search(r"['\"]([^'\"]{2,})['\"]", question or "")
    if quoted and "product" in q:
        spec.filters.append(FilterSpec("product_name", "contains", quoted.group(1)))

    output_terms = {
        "customer name": "customer_name", "product name": "product_name",
        "payment status": "payment_status", "order id": "order_id", "country": "country",
    }
    for term, name in output_terms.items():
        if term in q:
            spec.required_outputs.append(name)
    if "product" in q and any(term in q for term in ("no reviews", "never received feedback", "never received a review")):
        spec.required_outputs.append("product_review_status")
    n = re.search(r"\btop\s+(\d+)\b", q)
    if n:
        spec.top_n = int(n.group(1))
    if any(x in q for x in ("descending", "highest", "top ")):
        spec.sort_direction = "desc"
    elif "ascending" in q or "lowest" in q:
        spec.sort_direction = "asc"
    spec.is_complex = bool(any(x in q for x in ("compared", "versus", "vs ", "each month", "retention", "cohort", "rank", "percentile")))
    return spec
