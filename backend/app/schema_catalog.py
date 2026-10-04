"""Configuration-driven business metadata for the Data Genie schema.

This complements live SQLAlchemy reflection: reflection is authoritative for
types/FKs, while this catalog supplies business names, enum hints and concise
column descriptions for retrieval prompts.  Keeping it separate prevents a
large hard-coded schema prompt on every request.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class TableMetadata:
    description: str
    columns: Dict[str, str]
    enums: Dict[str, List[str]] = field(default_factory=dict)


CATALOG: Dict[str, TableMetadata] = {
    "categories": TableMetadata("Product merchandising categories.", {"category_id": "category key", "category_name": "display category", "parent_category_id": "parent category"}),
    "customers": TableMetadata("Store customers and their market segment.", {"customer_id": "customer key", "country": "customer country", "customer_segment": "commercial segment", "signup_date": "account creation date"}),
    "products": TableMetadata("Sellable catalog products.", {"product_id": "product key", "product_name": "product name", "category_id": "merchandising category", "unit_price": "current list price", "cost_price": "unit cost"}),
    "orders": TableMetadata("Customer purchase headers; one order has many order items.", {"order_id": "order key", "customer_id": "buyer", "order_date": "placed date", "status": "fulfilment status", "total_amount": "charged order total"}, {"status": ["pending", "processing", "shipped", "delivered", "cancelled", "returned"]}),
    "order_items": TableMetadata("Individual product lines sold on orders.", {"order_item_id": "line key", "order_id": "parent order", "product_id": "sold product", "quantity": "units", "line_total": "net line amount", "returned_quantity": "returned units"}),
    "payments": TableMetadata("Payment attempts and collections for orders.", {"payment_id": "payment key", "order_id": "paid order", "amount": "attempted amount", "status": "payment outcome", "payment_date": "payment date"}, {"status": ["succeeded", "failed", "refunded", "pending"]}),
    "product_reviews": TableMetadata("Customer product ratings and reviews.", {"review_id": "review key", "product_id": "reviewed product", "customer_id": "reviewer", "rating": "one to five rating", "review_date": "review date"}),
    "regions": TableMetadata("Sales and operating geographic regions.", {"region_id": "region key", "region_name": "region name", "country": "country"}),
    "departments": TableMetadata("Internal operating departments.", {"department_id": "department key", "department_name": "department name", "region_id": "operating region"}),
    "employees": TableMetadata("Employees responsible for sales and operations.", {"employee_id": "employee key", "department_id": "employing department", "employee_name": "employee name", "hire_date": "hire date"}),
    "suppliers": TableMetadata("Product suppliers.", {"supplier_id": "supplier key", "supplier_name": "supplier name", "region_id": "supplier region"}),
    "supplier_products": TableMetadata("Supplier-to-product sourcing relationship.", {"supplier_id": "supplier", "product_id": "product", "supplier_cost": "agreed unit cost"}),
    "warehouses": TableMetadata("Inventory fulfilment warehouses.", {"warehouse_id": "warehouse key", "warehouse_name": "warehouse name", "region_id": "warehouse region"}),
    "inventory": TableMetadata("Current on-hand and reorder inventory by product and warehouse.", {"inventory_id": "inventory key", "warehouse_id": "warehouse", "product_id": "stocked product", "quantity_on_hand": "available units", "reorder_level": "replenishment threshold"}),
    "shipments": TableMetadata("Outbound shipments for orders.", {"shipment_id": "shipment key", "order_id": "shipped order", "warehouse_id": "origin warehouse", "shipped_at": "ship timestamp", "status": "shipment status"}),
    "returns": TableMetadata("Customer return cases tied to orders and order items.", {"return_id": "return key", "order_id": "returned order", "order_item_id": "returned line", "return_date": "return date", "status": "return outcome"}),
    "invoices": TableMetadata("Billing invoices generated for orders.", {"invoice_id": "invoice key", "order_id": "invoiced order", "invoice_date": "invoice date", "amount_due": "invoice amount", "status": "invoice status"}),
    "campaigns": TableMetadata("Marketing campaigns.", {"campaign_id": "campaign key", "campaign_name": "campaign name", "start_date": "campaign start", "budget": "campaign budget"}),
    "campaign_members": TableMetadata("Customer campaign audience and conversion membership.", {"campaign_id": "campaign", "customer_id": "targeted customer", "joined_at": "enrollment date", "converted": "whether customer converted"}),
    "support_tickets": TableMetadata("Customer support cases.", {"ticket_id": "ticket key", "customer_id": "requesting customer", "order_id": "related order", "opened_at": "opened date", "status": "ticket status"}),
    "plans": TableMetadata("Subscription plans.", {"plan_id": "plan key", "plan_name": "plan name", "monthly_price": "monthly fee"}),
    "subscriptions": TableMetadata("Customer subscription lifecycle records.", {"subscription_id": "subscription key", "customer_id": "subscriber", "plan_id": "selected plan", "started_at": "start date", "status": "subscription status"}),
    "vendors": TableMetadata("Third-party service vendors such as logistics providers.", {"vendor_id": "vendor key", "vendor_name": "vendor name", "service_type": "provided service"}),
}


def logical_name(physical_name: str) -> str:
    return physical_name.removeprefix("dg_")


def metadata_for(physical_name: str) -> Optional[TableMetadata]:
    return CATALOG.get(logical_name(physical_name))
