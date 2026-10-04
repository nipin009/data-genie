"""Canonical physical table names (all prefixed with TABLE_PREFIX, default dg_).

Single source of truth so every module (metrics, fallback SQL, seeds, tests)
uses the same names. Logical name -> physical name, e.g. "orders" -> "dg_orders".
"""
from .config import get_settings

LOGICAL_TABLES = (
    "categories",
    "customers",
    "products",
    "orders",
    "order_items",
    "payments",
    "product_reviews",
    "regions", "departments", "employees", "suppliers", "supplier_products",
    "warehouses", "inventory", "shipments", "returns", "invoices",
    "campaigns", "campaign_members", "support_tickets", "plans",
    "subscriptions", "vendors",
)


def prefix() -> str:
    try:
        return get_settings().TABLE_PREFIX or ""
    except Exception:
        return "dg_"


def t(logical: str) -> str:
    """Physical table name for a logical name."""
    return f"{prefix()}{logical}"


def physical_tables() -> dict:
    return {name: t(name) for name in LOGICAL_TABLES}


# Convenient constants (resolved lazily via __getattr__ so tests can override prefix)
def __getattr__(name: str) -> str:
    mapping = {
        "CATEGORIES": "categories",
        "CUSTOMERS": "customers",
        "PRODUCTS": "products",
        "ORDERS": "orders",
        "ORDER_ITEMS": "order_items",
        "PAYMENTS": "payments",
        "REVIEWS": "product_reviews",
    }
    if name in mapping:
        return t(mapping[name])
    raise AttributeError(name)
