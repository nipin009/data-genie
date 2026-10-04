"""Synthetic seed generator: deterministic (seeded RNG) demo retail data.

Writes ONLY dg_-prefixed tables (dg_categories, dg_customers, dg_products,
dg_orders, dg_order_items, dg_payments, dg_product_reviews) into the local
Postgres database "local_db" (default DATABASE_URL). Existing non-dg_ tables
in local_db (other projects) are left untouched.

Usage:
  python -m scripts.seed_db [--rows-scale 1.0] [--database-url ...]
"""
import argparse
import datetime as dt
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import text  # noqa: E402

from app.db import get_engine, reset_engine  # noqa: E402

RNG = random.Random(42)

FIRST = ["Ava", "Liam", "Maya", "Noah", "Zoe", "Ethan", "Priya", "Lucas", "Amara", "Kai",
         "Sofia", "Mateo", "Yuki", "Omar", "Nina", "Diego", "Aisha", "Ravi", "Elena", "Tom"]
LAST = ["Sharma", "Garcia", "Kim", "Patel", "Nguyen", "Smith", "Khan", "Silva", "Muller", "Rossi",
        "Dubois", "Tanaka", "Ali", "Novak", "Costa", "Weber", "Fischer", "Haddad", "Ivanov", "Park"]
COUNTRIES = [("USA", "California", "San Francisco"), ("USA", "Texas", "Austin"), ("USA", "New York", "New York"),
             ("UK", "England", "London"), ("Germany", "Bavaria", "Munich"), ("India", "Karnataka", "Bengaluru"),
             ("Canada", "Ontario", "Toronto"), ("Australia", "NSW", "Sydney")]
SEGMENTS = ["premium", "standard", "budget", "enterprise"]
CATEGORIES = ["Electronics", "Apparel", "Home & Kitchen", "Sports", "Books", "Beauty", "Toys", "Grocery"]
BRANDS = ["Northwind", "Acme", "Globex", "Umbrella", "Initech", "Hooli", "Stark", "Wayne"]
STATUS = ["delivered", "delivered", "delivered", "shipped", "processing", "pending", "cancelled", "returned"]
PAY_METHODS = ["credit_card", "debit_card", "paypal", "bank_transfer", "cod"]
GATEWAYS = ["stripe", "adyen", "paypal", "razorpay"]


def _tables():
    try:
        from app.tables import t
        return {
            "cats": t("categories"), "cust": t("customers"), "prod": t("products"),
            "ord": t("orders"), "items": t("order_items"), "pay": t("payments"),
            "rev": t("product_reviews"),
            "regions": t("regions"), "deps": t("departments"), "employees": t("employees"),
            "suppliers": t("suppliers"), "supplier_products": t("supplier_products"),
            "warehouses": t("warehouses"), "inventory": t("inventory"), "shipments": t("shipments"),
            "returns": t("returns"), "invoices": t("invoices"), "campaigns": t("campaigns"),
            "campaign_members": t("campaign_members"), "tickets": t("support_tickets"),
            "plans": t("plans"), "subscriptions": t("subscriptions"), "vendors": t("vendors"),
        }
    except Exception:
        return {
            "cats": "dg_categories", "cust": "dg_customers", "prod": "dg_products",
            "ord": "dg_orders", "items": "dg_order_items", "pay": "dg_payments",
            "rev": "dg_product_reviews",
        }


def _ensure_local_db_dir(db_url=None) -> None:
    from app.config import get_settings
    url = db_url or os.getenv("DATABASE_URL") or get_settings().DATABASE_URL
    if url.startswith("sqlite:"):
        # sqlite:///./local_db/datagenie.db -> ./local_db/datagenie.db
        path = url.split("sqlite:///", 1)[-1]
        # resolve relative to backend/ (cwd may be backend/ or repo root)
        candidates = [os.path.join(os.getcwd(), path),
                      os.path.join(os.path.dirname(__file__), "..", path)]
        for cand in candidates:
            d = os.path.dirname(os.path.abspath(cand))
            if "local_db" in cand:
                os.makedirs(d, exist_ok=True)


def run(scale: float = 1.0, db_url=None):
    if db_url:
        os.environ["DATABASE_URL"] = db_url
        reset_engine()
    _ensure_local_db_dir(db_url)
    eng = get_engine(db_url)
    T = _tables()
    is_pg = eng.dialect.name == "postgresql"
    schema_path = os.path.join(os.path.dirname(__file__), "..", "data", "schema.sql")
    with open(schema_path) as f:
        ddl = f.read()
    with eng.begin() as conn:
        for stmt in [s.strip() for s in ddl.split(";") if s.strip()]:
            if not is_pg:
                stmt = stmt.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
            try:
                conn.execute(text(stmt))
            except Exception as e:
                print("DDL warn:", str(e)[:160])

    n_cust = int(120 * scale)
    n_prod = int(60 * scale)
    n_orders = int(600 * scale)
    # Anchor the synthetic timeline to TODAY so relative filters ("last 30 days",
    # "last 12 months") always hit data in local_db.
    today = dt.date.today()
    end = today
    start = end - dt.timedelta(days=1090)
    base = start  # earliest signup/product date

    with eng.begin() as conn:
        for key in ("subscriptions", "campaign_members", "tickets", "returns", "shipments", "invoices", "inventory", "supplier_products", "employees", "deps", "warehouses", "suppliers", "campaigns", "plans", "vendors", "regions"):
            try:
                conn.execute(text(f"DELETE FROM {T[key]}"))
            except Exception:
                pass
        for t in (T["rev"], T["pay"], T["items"], T["ord"], T["prod"], T["cust"], T["cats"]):
            try:
                conn.execute(text(f"DELETE FROM {t}"))
            except Exception:
                pass
        cat_ids = []
        for i, c in enumerate(CATEGORIES):
            r = conn.execute(text(
                f"INSERT INTO {T['cats']} (category_name, description, department, display_order, slug, tax_rate, manager_email)"
                " VALUES (:n, :d, :dep, :o, :s, :t, :e) RETURNING category_id" if is_pg else
                f"INSERT INTO {T['cats']} (category_name, description, department, display_order, slug, tax_rate, manager_email)"
                " VALUES (:n, :d, :dep, :o, :s, :t, :e)"),
                {"n": c, "d": f"{c} department", "dep": c, "o": i,
                 "s": c.lower().replace(" ", "-").replace("&", "and"), "t": 0.08, "e": f"{c.lower()[:4]}@store.com"})
            cat_ids.append(r.scalar() if is_pg else r.lastrowid)
        cust_ids = []
        for i in range(n_cust):
            fn, ln = RNG.choice(FIRST), RNG.choice(LAST)
            co, st, ci = RNG.choice(COUNTRIES)
            sd = base + dt.timedelta(days=RNG.randint(0, 900))
            params = {"fn": fn, "ln": ln, "em": f"{fn.lower()}.{ln.lower()}{i}@example.com",
                      "ph": f"+1-555-{RNG.randint(1000000,9999999)}",
                      "dob": (sd - dt.timedelta(days=RNG.randint(7000, 18000))).isoformat(),
                      "g": RNG.choice(["female", "male", "other"]), "co": co, "st": st, "ci": ci,
                      "pc": str(RNG.randint(10000, 99999)), "a1": f"{RNG.randint(10,999)} Main St",
                      "sd": sd.isoformat(), "seg": RNG.choice(SEGMENTS),
                      "tier": RNG.choice(["gold", "silver", "bronze"]), "ch": RNG.choice(["web", "mobile", "store"])}
            r = conn.execute(text(
                f"INSERT INTO {T['cust']} (first_name,last_name,email,phone,date_of_birth,gender,country,state,city,"
                "postal_code,address_line1,signup_date,customer_segment,lifetime_value_tier,preferred_channel)"
                " VALUES (:fn,:ln,:em,:ph,:dob,:g,:co,:st,:ci,:pc,:a1,:sd,:seg,:tier,:ch) RETURNING customer_id" if is_pg else
                f"INSERT INTO {T['cust']} (first_name,last_name,email,phone,date_of_birth,gender,country,state,city,"
                "postal_code,address_line1,signup_date,customer_segment,lifetime_value_tier,preferred_channel)"
                " VALUES (:fn,:ln,:em,:ph,:dob,:g,:co,:st,:ci,:pc,:a1,:sd,:seg,:tier,:ch)"), params)
            cust_ids.append(r.scalar() if is_pg else r.lastrowid)
        prod_ids = []
        for i in range(n_prod):
            cat = RNG.choice(cat_ids)
            brand = RNG.choice(BRANDS)
            price = round(RNG.uniform(9, 900), 2)
            cost = round(price * RNG.uniform(0.4, 0.7), 2)
            r = conn.execute(text(
                f"INSERT INTO {T['prod']} (sku,product_name,description,category_id,brand,unit_price,cost_price,weight_kg,"
                "color,size,material,created_at,supplier_name,warranty_months)"
                " VALUES (:sku,:nm,:d,:cat,:br,:p,:c,:w,:col,:sz,:m,:cr,:sup,:wm) RETURNING product_id" if is_pg else
                f"INSERT INTO {T['prod']} (sku,product_name,description,category_id,brand,unit_price,cost_price,weight_kg,"
                "color,size,material,created_at,supplier_name,warranty_months)"
                " VALUES (:sku,:nm,:d,:cat,:br,:p,:c,:w,:col,:sz,:m,:cr,:sup,:wm)"),
                {"sku": f"SKU-{i:05d}", "nm": f"{brand} {RNG.choice(['Pro','Max','Lite','Ultra','Classic'])} {i}",
                 "d": f"Quality {brand} product #{i}", "cat": cat, "br": brand, "p": price, "c": cost,
                 "w": round(RNG.uniform(0.1, 20), 2), "col": RNG.choice(["red", "blue", "black", "white", "green"]),
                 "sz": RNG.choice(["S", "M", "L", "XL"]), "m": RNG.choice(["cotton", "plastic", "metal", "wood"]),
                 "cr": (base + dt.timedelta(days=RNG.randint(0, 300))).isoformat(),
                 "sup": f"{brand} Supply", "wm": RNG.choice([6, 12, 24])})
            prod_ids.append((r.scalar() if is_pg else r.lastrowid, price))
        order_ids = []
        for i in range(n_orders):
            cust = RNG.choice(cust_ids)
            od = base + dt.timedelta(days=RNG.randint(300, 1090))
            status = RNG.choices(STATUS, weights=[46, 12, 10, 8, 10, 6, 4, 4])[0]
            ship = od + dt.timedelta(days=RNG.randint(1, 7)) if status in ("shipped", "delivered", "returned") else None
            n_items = RNG.randint(1, 4)
            subtotal = 0.0
            item_rows = []
            for _ in range(n_items):
                pid, price = RNG.choice(prod_ids)
                qty = RNG.randint(1, 5)
                disc = RNG.choice([0, 0, 0, 0.05, 0.1, 0.2])
                lt = round(qty * price * (1 - disc), 2)
                subtotal += lt
                item_rows.append((pid, qty, price, disc, lt))
            tax = round(subtotal * 0.08, 2)
            ship_cost = 0 if subtotal > 100 else 7.99
            disc_amt = round(subtotal * RNG.choice([0, 0, 0.05]), 2)
            total = round(subtotal + tax + ship_cost - disc_amt, 2)
            co, st, ci = RNG.choice(COUNTRIES)
            r = conn.execute(text(
                f"INSERT INTO {T['ord']} (customer_id,order_date,required_date,shipped_date,ship_country,ship_state,ship_city,"
                "status,payment_method,shipping_method,subtotal,tax_amount,shipping_cost,discount_amount,total_amount)"
                " VALUES (:c,:od,:rd,:sh,:co,:st,:ci,:s,:pm,:sm,:sub,:tax,:sc,:d,:t) RETURNING order_id" if is_pg else
                f"INSERT INTO {T['ord']} (customer_id,order_date,required_date,shipped_date,ship_country,ship_state,ship_city,"
                "status,payment_method,shipping_method,subtotal,tax_amount,shipping_cost,discount_amount,total_amount)"
                " VALUES (:c,:od,:rd,:sh,:co,:st,:ci,:s,:pm,:sm,:sub,:tax,:sc,:d,:t)"),
                {"c": cust, "od": od.isoformat(), "rd": (od + dt.timedelta(days=10)).isoformat(),
                 "sh": ship.isoformat() if ship else None, "co": co, "st": st, "ci": ci, "s": status,
                 "pm": RNG.choice(PAY_METHODS), "sm": RNG.choice(["standard", "express", "overnight"]),
                 "sub": subtotal, "tax": tax, "sc": ship_cost, "d": disc_amt, "t": total})
            oid = r.scalar() if is_pg else r.lastrowid
            order_ids.append((oid, cust, od, total, status))
            for pid, qty, price, disc, lt in item_rows:
                conn.execute(text(
                    f"INSERT INTO {T['items']} (order_id,product_id,quantity,unit_price,discount_pct,tax_pct,line_total,"
                    "returned_quantity,fulfillment_status,warehouse_code) VALUES (:o,:p,:q,:u,:d,0.08,:lt,:rq,:f,:w)"),
                    {"o": oid, "p": pid, "q": qty, "u": price, "d": disc, "lt": lt,
                     "rq": qty if (status == "returned" and RNG.random() < 0.5) else 0,
                     "f": "returned" if status == "returned" else "fulfilled",
                     "w": RNG.choice(["WH-EAST", "WH-WEST", "WH-EU"])})
            pstatus = "failed" if RNG.random() < 0.06 else ("refunded" if status == "returned" else "succeeded")
            conn.execute(text(
                f"INSERT INTO {T['pay']} (order_id,customer_id,payment_date,amount,payment_method,transaction_id,status,"
                "gateway,billing_country,billing_city,failure_reason,refunded_amount)"
                " VALUES (:o,:c,:d,:a,:m,:t,:s,:g,:bc,:bci,:fr,:rf)"),
                {"o": oid, "c": cust, "d": od.isoformat(), "a": total, "m": RNG.choice(PAY_METHODS),
                 "t": f"txn-{oid}-{RNG.randint(1000,9999)}", "s": pstatus, "g": RNG.choice(GATEWAYS),
                 "bc": co, "bci": ci, "fr": "card_declined" if pstatus == "failed" else None,
                 "rf": total if pstatus == "refunded" else 0})
        for _ in range(int(n_orders * 0.7)):
            oid, cust, od, total, status = RNG.choice(order_ids)
            pid = RNG.choice(prod_ids)[0]
            rating = RNG.choices([5, 4, 3, 2, 1], weights=[45, 25, 15, 8, 7])[0]
            conn.execute(text(
                f"INSERT INTO {T['rev']} (product_id,customer_id,order_id,rating,title,body,review_date,"
                "helpful_votes,verified_purchase,sentiment) VALUES (:p,:c,:o,:r,:t,:b,:d,:h,:v,:s)"),
                {"p": pid, "c": cust, "o": oid, "r": rating, "t": f"{'Great' if rating>=4 else 'Okay' if rating==3 else 'Poor'} product",
                 "b": f"Review body rating {rating}", "d": (od + dt.timedelta(days=RNG.randint(1, 60))).isoformat(),
                 "h": RNG.randint(0, 50), "v": True, "s": "positive" if rating >= 4 else ("neutral" if rating == 3 else "negative")})
        # Connected operational records make multi-table joins meaningful.
        for name, country in [("North America", "USA"), ("Europe", "Germany"), ("Asia Pacific", "India")]:
            conn.execute(text(f"INSERT INTO {T['regions']} (region_name,country) VALUES (:n,:c)"), {"n": name, "c": country})
        region_ids = [r[0] for r in conn.execute(text(f"SELECT region_id FROM {T['regions']}"))]
        for name in ("Sales", "Operations", "Support"):
            conn.execute(text(f"INSERT INTO {T['deps']} (department_name,region_id) VALUES (:n,:r)"), {"n": name, "r": RNG.choice(region_ids)})
        dep_ids = [r[0] for r in conn.execute(text(f"SELECT department_id FROM {T['deps']}"))]
        for i in range(12): conn.execute(text(f"INSERT INTO {T['employees']} (employee_name,department_id,hire_date) VALUES (:n,:d,:h)"), {"n": f"Employee {i+1}", "d": RNG.choice(dep_ids), "h": (base + dt.timedelta(days=i*30)).isoformat()})
        for i, brand in enumerate(BRANDS[:5]): conn.execute(text(f"INSERT INTO {T['suppliers']} (supplier_name,region_id) VALUES (:n,:r)"), {"n": f"{brand} Supply", "r": RNG.choice(region_ids)})
        supplier_ids = [r[0] for r in conn.execute(text(f"SELECT supplier_id FROM {T['suppliers']}"))]
        for pid, price in prod_ids: conn.execute(text(f"INSERT INTO {T['supplier_products']} (supplier_id,product_id,supplier_cost) VALUES (:s,:p,:c)"), {"s": RNG.choice(supplier_ids), "p": pid, "c": round(price * .55, 2)})
        for name in ("East DC", "West DC", "Europe DC"):
            conn.execute(text(f"INSERT INTO {T['warehouses']} (warehouse_name,region_id) VALUES (:n,:r)"), {"n": name, "r": RNG.choice(region_ids)})
        warehouse_ids = [r[0] for r in conn.execute(text(f"SELECT warehouse_id FROM {T['warehouses']}"))]
        for pid, _ in prod_ids:
            conn.execute(text(f"INSERT INTO {T['inventory']} (warehouse_id,product_id,quantity_on_hand,reorder_level) VALUES (:w,:p,:q,:l)"), {"w": RNG.choice(warehouse_ids), "p": pid, "q": RNG.randint(10, 200), "l": RNG.randint(5, 30)})
        for oid, cust, od, total, status in order_ids:
            conn.execute(text(f"INSERT INTO {T['invoices']} (order_id,invoice_date,amount_due,status) VALUES (:o,:d,:a,:s)"), {"o": oid, "d": od.isoformat(), "a": total, "s": "paid" if status not in ("cancelled",) else "void"})
            if status in ("shipped", "delivered", "returned"): conn.execute(text(f"INSERT INTO {T['shipments']} (order_id,warehouse_id,shipped_at,status) VALUES (:o,:w,:d,:s)"), {"o": oid, "w": RNG.choice(warehouse_ids), "d": od.isoformat(), "s": "delivered" if status != "shipped" else "in_transit"})
        item_ids = [r[0] for r in conn.execute(text(f"SELECT order_item_id FROM {T['items']} WHERE returned_quantity > 0"))]
        for item_id in item_ids: conn.execute(text(f"INSERT INTO {T['returns']} (order_id,order_item_id,return_date,status) SELECT order_id,:i,:d,'received' FROM {T['items']} WHERE order_item_id=:i"), {"i": item_id, "d": today.isoformat()})
        for name, budget in [("Spring Launch", 25000), ("VIP Retention", 12000)]: conn.execute(text(f"INSERT INTO {T['campaigns']} (campaign_name,start_date,budget) VALUES (:n,:d,:b)"), {"n": name, "d": base.isoformat(), "b": budget})
        campaign_ids = [r[0] for r in conn.execute(text(f"SELECT campaign_id FROM {T['campaigns']}"))]
        for cid in campaign_ids:
            for customer_id in RNG.sample(cust_ids, min(30, len(cust_ids))): conn.execute(text(f"INSERT INTO {T['campaign_members']} (campaign_id,customer_id,joined_at,converted) VALUES (:c,:u,:d,:v)"), {"c": cid, "u": customer_id, "d": base.isoformat(), "v": RNG.random() < .25})
        for customer_id in RNG.sample(cust_ids, min(40, len(cust_ids))): conn.execute(text(f"INSERT INTO {T['tickets']} (customer_id,order_id,opened_at,status) VALUES (:c,:o,:d,:s)"), {"c": customer_id, "o": RNG.choice(order_ids)[0], "d": today.isoformat(), "s": RNG.choice(["open", "pending", "closed"])})
        for name, price in [("Basic", 9), ("Pro", 29), ("Enterprise", 99)]: conn.execute(text(f"INSERT INTO {T['plans']} (plan_name,monthly_price) VALUES (:n,:p)"), {"n": name, "p": price})
        plan_ids = [r[0] for r in conn.execute(text(f"SELECT plan_id FROM {T['plans']}"))]
        for customer_id in RNG.sample(cust_ids, min(50, len(cust_ids))): conn.execute(text(f"INSERT INTO {T['subscriptions']} (customer_id,plan_id,started_at,status) VALUES (:c,:p,:d,:s)"), {"c": customer_id, "p": RNG.choice(plan_ids), "d": base.isoformat(), "s": RNG.choice(["active", "active", "cancelled"])})
        for name, service in [("Swift Logistics", "shipping"), ("CloudPay", "payments")]: conn.execute(text(f"INSERT INTO {T['vendors']} (vendor_name,service_type) VALUES (:n,:s)"), {"n": name, "s": service})
    print(f"Seeded scale={scale}: {n_cust} customers, {n_prod} products, {n_orders} orders -> local_db {list(T.values())} on {eng.url!r}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--rows-scale", type=float, default=1.0)
    ap.add_argument("--database-url", default=None)
    args = ap.parse_args()
    run(scale=args.rows_scale, db_url=args.database_url)
