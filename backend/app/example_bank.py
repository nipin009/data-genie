"""Curated reusable Question→SQL examples, retrieved by lexical relevance."""
from dataclasses import dataclass
import re
from typing import List


@dataclass(frozen=True)
class SqlExample:
    question: str
    sql: str
    tags: tuple[str, ...]


EXAMPLES = [
    SqlExample("Top products by revenue", "SELECT p.product_name, SUM(oi.line_total) revenue FROM dg_order_items oi JOIN dg_products p ON p.product_id=oi.product_id GROUP BY 1 ORDER BY 2 DESC LIMIT 10", ("product", "revenue", "top", "join", "group")),
    SqlExample("Monthly revenue trend", "SELECT date_trunc('month', o.order_date) month, SUM(oi.line_total) revenue FROM dg_orders o JOIN dg_order_items oi ON oi.order_id=o.order_id GROUP BY 1 ORDER BY 1", ("monthly", "trend", "revenue", "date")),
    SqlExample("Customers with above-average spend", "WITH spend AS (SELECT customer_id, SUM(total_amount) total FROM dg_orders GROUP BY 1) SELECT customer_id,total FROM spend WHERE total > (SELECT AVG(total) FROM spend)", ("customer", "subquery", "cte", "average", "spend")),
    SqlExample("Rank warehouses by inventory value", "SELECT w.warehouse_name, SUM(i.quantity_on_hand*p.cost_price) value, RANK() OVER (ORDER BY SUM(i.quantity_on_hand*p.cost_price) DESC) rank FROM dg_inventory i JOIN dg_warehouses w ON w.warehouse_id=i.warehouse_id JOIN dg_products p ON p.product_id=i.product_id GROUP BY 1", ("warehouse", "inventory", "value", "rank", "window")),
    SqlExample("Campaign conversion rate", "SELECT c.campaign_name, AVG(CASE WHEN cm.converted THEN 1.0 ELSE 0 END) conversion_rate FROM dg_campaign_members cm JOIN dg_campaigns c ON c.campaign_id=cm.campaign_id GROUP BY 1 HAVING COUNT(*) > 0", ("campaign", "conversion", "having", "conditional")),
    SqlExample("Open support tickets by region", "SELECT r.region_name, COUNT(*) tickets FROM dg_support_tickets t JOIN dg_customers c ON c.customer_id=t.customer_id JOIN dg_regions r ON r.country=c.country WHERE t.status <> 'closed' GROUP BY 1", ("support", "ticket", "region", "join", "null")),
]


def retrieve_examples(question: str, limit: int = 3) -> List[SqlExample]:
    tokens = set(re.findall(r"[a-z0-9]+", question.lower()))
    scored = [(sum(tag in tokens for tag in e.tags), e) for e in EXAMPLES]
    return [e for score, e in sorted(scored, key=lambda item: item[0], reverse=True) if score][:limit]


def examples_context(question: str) -> str:
    found = retrieve_examples(question)
    if not found:
        return ""
    return "QUESTION→SQL EXAMPLES (adapt only with retrieved tables/columns):\n" + "\n".join(f"- Q: {e.question}\n  SQL: {e.sql}" for e in found)
