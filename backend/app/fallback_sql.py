"""Deterministic fallback SQL builder (used when no Gemini key is set).

Covers common benchmark patterns: revenue/order counts, top products, orders by
status/date, customer lookups, reviews/ratings, payments. Always emits a single
read-only SELECT with LIMIT against dg_-prefixed tables in local_db.
The validator still checks its output.
"""
import re


def _tbl(logical: str) -> str:
    try:
        from .tables import t
        return t(logical)
    except Exception:
        return f"dg_{logical}"


def _limit(sql: str, n: int = 100) -> str:
    if re.search(r"\blimit\s+\d+", sql, re.I):
        return sql
    return sql.rstrip().rstrip(";") + f" LIMIT {n}"


def _month_expr() -> str:
    """Month-truncation expression portable to the configured local_db dialect."""
    try:
        import os as _os
        url = _os.getenv("DATABASE_URL", "")
        if not url:
            try:
                from .config import get_settings as _gs
                url = _gs().DATABASE_URL
            except Exception:
                url = ""
        if url.startswith("sqlite"):
            return "strftime('%Y-%m', o.order_date)"
    except Exception:
        pass
    return "to_char(o.order_date, 'YYYY-MM')"


def _like() -> str:
    try:
        import os as _os
        url = _os.getenv("DATABASE_URL", "")
        if url.startswith("sqlite"):
            return "LIKE"
    except Exception:
        pass
    return "ILIKE"


def build_fallback_sql(question: str, schema_context: str = "") -> str:
    q = question.lower()
    has = lambda *ws: any(w in q for w in ws)
    ORD, ITEMS, CUST, PROD, CATS, PAY, REV = (
        _tbl("orders"), _tbl("order_items"), _tbl("customers"), _tbl("products"),
        _tbl("categories"), _tbl("payments"), _tbl("product_reviews"),
    )
    LIKE = _like()

    # Detailed order listing.  This must precede generic order/customer rules.
    if has("order") and has("customer name") and has("product name") and has("payment status"):
        return _limit(f"""SELECT o.order_id, o.order_date,
c.first_name || ' ' || c.last_name AS customer_name, p.product_name,
pay.status AS payment_status
FROM {ORD} o JOIN {CUST} c ON c.customer_id = o.customer_id
JOIN {ITEMS} oi ON oi.order_id = o.order_id
JOIN {PROD} p ON p.product_id = oi.product_id
LEFT JOIN {PAY} pay ON pay.order_id = o.order_id
ORDER BY o.order_date DESC""")

    # Specific product lookup (quoted name or explicit SKU-ish token) -> filtered, may return 0 rows honestly
    mquoted = re.search(r"'([^']{3,})'|\"([^\"]{3,})\"", question)
    if has("product") and mquoted and has("revenue", "sales", "total", "rating", "review", "order", "price"):
        name = (mquoted.group(1) or mquoted.group(2)).replace("'", "''")
        where = _date_filter(q, "o.order_date")
        return _limit(f"""SELECT p.product_name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS revenue,
COUNT(DISTINCT o.order_id) AS orders
FROM {ITEMS} oi JOIN {PROD} p ON p.product_id = oi.product_id
LEFT JOIN {ORD} o ON o.order_id = oi.order_id
WHERE p.product_name {LIKE} '%{name}%' ESCAPE '\\'{where}
GROUP BY p.product_name ORDER BY revenue DESC""")

    # Top products by RETURN RATE (must precede generic top-products branch)
    if has("top") and has("product") and has("return", "refund rate", "return rate"):
        n = _top_n(q, 3)
        return _limit(f"""SELECT p.product_name,
SUM(oi.returned_quantity) * 1.0 / NULLIF(SUM(oi.quantity), 0) AS return_rate,
SUM(oi.quantity) AS units_sold
FROM {ITEMS} oi JOIN {PROD} p ON p.product_id = oi.product_id
GROUP BY p.product_name HAVING SUM(oi.quantity) > 0 ORDER BY return_rate DESC LIMIT {n}""", n)

    # Rating by category must precede generic category/revenue matching.
    if has("rating", "review", "stars") and has("categor"):
        return _limit(f"""SELECT cat.category_name, AVG(r.rating) AS avg_rating, COUNT(*) AS reviews
FROM {REV} r JOIN {PROD} p ON p.product_id = r.product_id
JOIN {CATS} cat ON cat.category_id = p.category_id
GROUP BY cat.category_name ORDER BY avg_rating DESC""")
    # Category revenue breakdown (before generic revenue-total so "revenue by category" groups correctly)
    if has("categor") and has("revenue", "sales", "gmv", "total", "by", "breakdown"):
        return _limit(f"""SELECT cat.category_name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS revenue
FROM {ITEMS} oi JOIN {PROD} p ON p.product_id = oi.product_id
JOIN {CATS} cat ON cat.category_id = p.category_id
GROUP BY cat.category_name ORDER BY revenue DESC""")

    # Common commercial breakdowns.  These must precede the total-revenue
    # branch; otherwise a clear request such as "revenue by country" used to
    # receive a plausible but incorrect single total.
    if has("revenue", "sales", "gmv") and has("country"):
        where = _date_filter(q, "o.order_date")
        return _limit(f"""SELECT c.country, SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS revenue
FROM {ORD} o JOIN {CUST} c ON c.customer_id = o.customer_id
JOIN {ITEMS} oi ON oi.order_id = o.order_id
WHERE 1=1{where}
GROUP BY c.country ORDER BY revenue DESC""")
    if has("revenue", "sales", "gmv") and has("segment"):
        where = _date_filter(q, "o.order_date")
        return _limit(f"""SELECT c.customer_segment, SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS revenue
FROM {ORD} o JOIN {CUST} c ON c.customer_id = o.customer_id
JOIN {ITEMS} oi ON oi.order_id = o.order_id
WHERE 1=1{where}
GROUP BY c.customer_segment ORDER BY revenue DESC""")
    if has("revenue", "sales", "gmv") and has("brand"):
        where = _date_filter(q, "o.order_date")
        return _limit(f"""SELECT p.brand, SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS revenue
FROM {ORD} o JOIN {ITEMS} oi ON oi.order_id = o.order_id
JOIN {PROD} p ON p.product_id = oi.product_id
WHERE 1=1{where}
GROUP BY p.brand ORDER BY revenue DESC""")
    if has("revenue", "sales", "gmv") and has("product") and has("by", "breakdown", "each"):
        where = _date_filter(q, "o.order_date")
        return _limit(f"""SELECT p.product_name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS revenue
FROM {ORD} o JOIN {ITEMS} oi ON oi.order_id = o.order_id
JOIN {PROD} p ON p.product_id = oi.product_id
WHERE 1=1{where}
GROUP BY p.product_name ORDER BY revenue DESC""")

    # Top products by revenue
    if has("top") and has("product"):
        n = _top_n(q, 5)
        return _limit(f"""SELECT p.product_name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS revenue
FROM {ITEMS} oi JOIN {PROD} p ON p.product_id = oi.product_id
GROUP BY p.product_name ORDER BY revenue DESC LIMIT {n}""", n)
    # AOV by segment
    if has("average order", "aov") and has("segment"):
        return _limit(f"""SELECT c.customer_segment, AVG(o.total_amount) AS avg_order_value, COUNT(*) AS orders
FROM {ORD} o JOIN {CUST} c ON c.customer_id = o.customer_id
GROUP BY c.customer_segment ORDER BY avg_order_value DESC""")
    # Revenue total / by month
    if has("revenue", "sales", "gmv") and has("month"):
        mexpr = _month_expr()
        where = _date_filter(q, "o.order_date")
        return _limit(f"""SELECT {mexpr} AS month,
SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS revenue
FROM {ORD} o JOIN {ITEMS} oi ON oi.order_id = o.order_id
WHERE 1=1{where}
GROUP BY 1 ORDER BY 1""")
    # Do not convert an unimplemented breakdown into a total.  A wrong answer
    # that looks plausible is worse than an explicit capability response.
    if has("revenue", "sales", "gmv") and has("by ", "breakdown", "each ", "per "):
        return ""
    if has("trend", "over time", "monthly", "by month"):
        mexpr = _month_expr()
        return _limit(f"""SELECT {mexpr} AS month, COUNT(*) AS orders,
SUM(o.total_amount) AS revenue FROM {ORD} o GROUP BY 1 ORDER BY 1""")
    if has("revenue", "sales", "gmv", "total"):
        where = _date_filter(q, "o.order_date")
        return _limit(f"""SELECT SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS total_revenue,
COUNT(DISTINCT o.order_id) AS orders
FROM {ORD} o JOIN {ITEMS} oi ON oi.order_id = o.order_id{where}""")
    # Order count / AOV
    if has("order") and has("by ", "breakdown", "each ", "per ") and has("count", "how many", "number"):
        return ""
    if has("how many orders", "order count", "number of orders", "count") and has("order"):
        where = _date_filter(q, "o.order_date")
        extra = f" AND o.status {LIKE} '%deliver%'" if has("deliver") else ""
        return _limit(f"SELECT COUNT(*) AS order_count FROM {ORD} o WHERE 1=1{extra}{where}".replace("WHERE 1=1 AND", "WHERE").replace("WHERE 1=1", ""))
    if has("average order", "aov"):
        return _limit(f"SELECT AVG(o.total_amount) AS avg_order_value FROM {ORD} o")
    # Orders list w/ status
    if has("order") and has("pending", "shipped", "deliver", "cancel", "processing", "return"):
        status = "pending" if "pending" in q else ("delivered" if "deliver" in q else ("shipped" if "ship" in q else ("cancelled" if "cancel" in q else "processing")))
        where = _date_filter(q, "o.order_date")
        return _limit(f"SELECT o.order_id, o.order_date, o.status, o.total_amount FROM {ORD} o WHERE o.status = '{status}'{where} ORDER BY o.order_date DESC")
    if has("order") and has("status") and has("by", "breakdown", "count"):
        where = _date_filter(q, "o.order_date")
        return _limit(f"SELECT o.status, COUNT(*) AS order_count FROM {ORD} o WHERE 1=1{where} GROUP BY o.status ORDER BY order_count DESC")
    # Customers
    if has("customer") and has("top", "best", "most", "lifetime", "spend"):
        n = _top_n(q, 5)
        country = ", c.country" if "country" in q else ""
        country_group = ", c.country" if "country" in q else ""
        where = _date_filter(q, "o.order_date")
        return _limit(f"""SELECT c.customer_id, c.first_name || ' ' || c.last_name AS customer_name, SUM(o.total_amount) AS lifetime_spend
{country}
FROM {CUST} c JOIN {ORD} o ON o.customer_id = c.customer_id WHERE 1=1{where}
GROUP BY c.customer_id, c.first_name, c.last_name{country_group} ORDER BY lifetime_spend DESC LIMIT {n}""", n)
    if has("customer") and has("country", "by country", "segment"):
        return _limit(f"SELECT c.country, COUNT(*) AS customers FROM {CUST} c GROUP BY 1 ORDER BY customers DESC")
    if has("customer"):
        return _limit(f"SELECT c.customer_id, c.first_name, c.last_name, c.country, c.customer_segment FROM {CUST} c ORDER BY c.signup_date DESC")
    # Category breakdown
    if has("categor"):
        return _limit(f"""SELECT cat.category_name, SUM(oi.quantity * oi.unit_price * (1 - oi.discount_pct)) AS revenue
FROM {ITEMS} oi JOIN {PROD} p ON p.product_id = oi.product_id
JOIN {CATS} cat ON cat.category_id = p.category_id
GROUP BY cat.category_name ORDER BY revenue DESC""")
    # Reviews / ratings
    if has("rating", "review", "stars"):
        if has("average", "avg"):
            return _limit(f"SELECT AVG(r.rating) AS avg_rating FROM {REV} r")
        return _limit(f"SELECT r.review_id, r.product_id, r.rating, r.title, r.review_date FROM {REV} r ORDER BY r.review_date DESC")
    # Payments
    if has("payment", "refund", "failed"):
        if has("by method", "by payment method", "payment method") and has("count", "total", "amount", "revenue", "breakdown"):
            return _limit(f"SELECT p.payment_method, COUNT(*) AS payment_count, SUM(p.amount) AS payment_amount FROM {PAY} p GROUP BY p.payment_method ORDER BY payment_amount DESC")
        if "fail" in q:
            return _limit(f"SELECT p.payment_id, p.order_id, p.amount, p.payment_method, p.status FROM {PAY} p WHERE p.status = 'failed' ORDER BY p.payment_date DESC")
        return _limit(f"SELECT p.payment_id, p.order_id, p.amount, p.payment_method, p.status, p.payment_date FROM {PAY} p ORDER BY p.payment_date DESC")
    # Product list
    if has("product") and has("list", "show", "all"):
        return _limit(f"SELECT p.product_id, p.product_name, p.brand, p.unit_price FROM {PROD} p WHERE p.is_active = TRUE ORDER BY p.product_name")
    # Empty signals that the deterministic, offline builder has no faithful
    # template.  The graph turns this into a transparent response instead of
    # executing an unrelated default query.
    return ""


def _top_n(q: str, default: int) -> int:
    m = re.search(r"top\s+(\d+)", q)
    if m:
        try:
            return max(1, min(int(m.group(1)), 100))
        except Exception:
            pass
    return default


def _is_sqlite() -> bool:
    try:
        import os as _os
        url = _os.getenv("DATABASE_URL", "")
        if not url:
            try:
                from .config import get_settings as _gs
                url = _gs().DATABASE_URL
            except Exception:
                url = ""
        return url.startswith("sqlite")
    except Exception:
        return False


def _date_filter(q: str, col: str) -> str:
    m = re.search(r"(20\d{2})-(\d{2})-(\d{2}).*(20\d{2})-(\d{2})-(\d{2})", q)
    if m:
        return f" AND {col} BETWEEN '{m.group(1)}-{m.group(2)}-{m.group(3)}' AND '{m.group(4)}-{m.group(5)}-{m.group(6)}'"
    m2 = re.search(r"last\s+(\d+)\s+days?", q)
    if m2:
        n = int(m2.group(1))
        if _is_sqlite():
            return f" AND {col} >= date('now', '-{n} days')"
        return f" AND {col} >= CURRENT_DATE - INTERVAL '{n} days'"
    m_months = re.search(r"last\s+(\d+)\s+months?", q)
    if m_months:
        n = int(m_months.group(1))
        if _is_sqlite():
            return f" AND {col} >= date('now', '-{n} months')"
        return f" AND {col} >= CURRENT_DATE - INTERVAL '{n} months'"
    m3 = re.search(r"\b(20\d{2})\b", q)
    if m3 and ("year" in q or "in 20" in q):
        y = m3.group(1)
        return f" AND {col} >= '{y}-01-01' AND {col} < '{int(y)+1}-01-01'"
    return ""


def repair_fallback_sql(bad_sql: str, error: str) -> str:
    """Minimal deterministic repair: strip multi-statements, add LIMIT, safe default on garbage."""
    import re as _re
    try:
        from .tables import t as _t
        _ord = _t("orders")
    except Exception:
        _ord = "dg_orders"
    sql = (bad_sql or "").strip().rstrip(";")
    sql = sql.split(";")[0]
    if not sql or not _re.search(r"\bselect\b", sql, _re.I):
        return f"SELECT o.order_id, o.order_date, o.status, o.total_amount FROM {_ord} o ORDER BY o.order_date DESC LIMIT 100"
    if not _re.search(r"\blimit\s+\d+", sql, _re.I):
        sql += " LIMIT 500"
    return sql
