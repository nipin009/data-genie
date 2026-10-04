"""Business metric definitions (semantic layer).

Metrics map friendly names to grounded SQL expressions. The SQL generator may
use these to avoid guessing formulas (e.g. revenue = SUM(line_total)).
Each metric records required tables/columns so retrieval can include them.

Physical table names carry the dg_ prefix (see app.tables); logical names are
kept for keyword matching.
"""
from dataclasses import dataclass
from typing import Dict, List


@dataclass(frozen=True)
class Metric:
    name: str
    description: str
    expression: str  # SQL fragment (aggregate)
    tables: List[str]  # physical dg_ names
    synonyms: List[str]


def _t(logical: str) -> str:
    from .tables import t as _physical
    return _physical(logical)


def _build_metrics() -> List[Metric]:
    CATS, CUST, PROD, ORD, ITEMS, PAY, REV = (
        _t("categories"), _t("customers"), _t("products"), _t("orders"),
        _t("order_items"), _t("payments"), _t("product_reviews"),
    )
    INVENTORY, RETURNS = _t("inventory"), _t("returns")
    return [
        Metric("total_revenue", "Sum of order line totals net of item discounts",
               "SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct))",
               [ITEMS, ORD], ["revenue", "sales", "turnover", "gmv", "income"]),
        Metric("net_revenue_after_returns", "Revenue after item discounts and returned units",
               "SUM((oi.quantity - oi.returned_quantity) * oi.unit_price * (1 - oi.discount_pct))",
               [ITEMS, ORD], ["net of returns", "net revenue", "revenue after returns"]),
        Metric("total_orders", "Count of orders", "COUNT(DISTINCT o.order_id)",
               [ORD], ["orders", "order count", "number of orders"]),
        Metric("avg_order_value", "Average order total (AOV)",
               "AVG(o.total_amount)", [ORD], ["aov", "average order value", "average order"]),
        Metric("total_quantity", "Total units sold", "SUM(oi.quantity)",
               [ITEMS], ["units sold", "quantity sold", "items sold"]),
        Metric("avg_rating", "Average product rating", "AVG(r.rating)",
               [REV], ["rating", "average rating", "stars"]),
        Metric("products_without_reviews", "Products with no associated customer review",
               f"LEFT JOIN {REV} r ON r.product_id = p.product_id WHERE r.review_id IS NULL",
               [PROD, REV], ["no reviews", "without reviews", "never received feedback", "without feedback"]),
        Metric("total_payments", "Sum of successful payments", "SUM(p.amount)",
               [PAY], ["payments", "collected", "cash collected"]),
        Metric("refund_rate", "Share of order items returned",
               "SUM(oi.returned_quantity) * 1.0 / NULLIF(SUM(oi.quantity),0)",
               [ITEMS], ["return rate", "refund rate", "returns"]),
        Metric("active_customers", "Count of distinct customers with orders",
               "COUNT(DISTINCT o.customer_id)", [ORD, CUST],
               ["customers", "active customers", "buyers"]),
        Metric("discount_given", "Total discount amount on orders",
               "SUM(o.discount_amount)", [ORD], ["discount", "discounts given"]),
        Metric("completed_orders", "Count of delivered orders", "COUNT(*) FILTER (WHERE o.status = 'delivered')",
               [ORD], ["completed orders", "delivered orders"]),
        Metric("returned_orders", "Count of distinct orders with a return case", "COUNT(DISTINCT r.order_id)",
               [RETURNS], ["returned order", "returned orders"]),
        Metric("inventory_value", "On-hand inventory valued at product cost", "SUM(i.quantity_on_hand * p.cost_price)",
               [INVENTORY, PROD], ["inventory value", "stock value"]),
        Metric("customer_lifetime_value", "Lifetime completed order spend per customer", "SUM(o.total_amount)",
               [ORD, CUST], ["customer lifetime value", "clv", "lifetime spend"]),
    ]


def _metrics() -> List[Metric]:
    return _build_metrics()


# Backwards-compat: module-level list built with default prefix.
METRICS: List[Metric] = _build_metrics()

METRIC_INDEX: Dict[str, Metric] = {m.name: m for m in METRICS}


def find_metrics(question: str) -> List[Metric]:
    q = question.lower()
    hits = []
    for m in _metrics():
        if m.name.replace("_", " ") in q:
            hits.append(m)
            continue
        for syn in m.synonyms:
            if syn in q:
                hits.append(m)
                break
    # "Revenue net of returns" has a canonical definition and must not send
    # contradictory gross and net formulas to the generator.
    if any(phrase in q for phrase in ("net of returns", "net revenue", "revenue after returns")):
        hits = [m for m in hits if m.name not in {"total_revenue", "refund_rate"}]
    return hits


def metrics_context(metrics: List[Metric]) -> str:
    if not metrics:
        return "No predefined business metric matched; use schema columns directly."
    lines = ["BUSINESS METRICS (use these expressions verbatim when applicable):"]
    for m in metrics:
        lines.append(f"- {m.name}: {m.description} => {m.expression}  [tables: {', '.join(m.tables)}]")
    return "\n".join(lines)
