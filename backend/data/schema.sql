-- Data Genie schema: 7 tables with dg_ prefix, 15-20 columns each, FK join graph.
-- Lives in local_db (SQLite file backend/local_db/datagenie.db for dev, Postgres for prod).
-- PostgreSQL dialect (also compatible with SQLite seed path via SQLAlchemy DDL).

CREATE TABLE IF NOT EXISTS dg_categories (
  category_id SERIAL PRIMARY KEY,
  category_name VARCHAR(100) NOT NULL UNIQUE,
  description TEXT,
  parent_category_id INTEGER REFERENCES dg_categories(category_id),
  department VARCHAR(80),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATE NOT NULL DEFAULT CURRENT_DATE,
  updated_at DATE,
  image_url VARCHAR(300),
  display_order INTEGER DEFAULT 0,
  slug VARCHAR(120) UNIQUE,
  meta_title VARCHAR(160),
  meta_description VARCHAR(300),
  tax_rate NUMERIC(5,4) DEFAULT 0.08,
  manager_email VARCHAR(160),
  notes TEXT
);

CREATE TABLE IF NOT EXISTS dg_customers (
  customer_id SERIAL PRIMARY KEY,
  first_name VARCHAR(80) NOT NULL,
  last_name VARCHAR(80) NOT NULL,
  email VARCHAR(160) NOT NULL UNIQUE,
  phone VARCHAR(40),
  date_of_birth DATE,
  gender VARCHAR(20),
  country VARCHAR(80),
  state VARCHAR(80),
  city VARCHAR(100),
  postal_code VARCHAR(20),
  address_line1 VARCHAR(200),
  address_line2 VARCHAR(200),
  signup_date DATE NOT NULL DEFAULT CURRENT_DATE,
  customer_segment VARCHAR(40),
  lifetime_value_tier VARCHAR(20),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  preferred_channel VARCHAR(30)
);

CREATE TABLE IF NOT EXISTS dg_products (
  product_id SERIAL PRIMARY KEY,
  sku VARCHAR(60) NOT NULL UNIQUE,
  product_name VARCHAR(160) NOT NULL,
  description TEXT,
  category_id INTEGER NOT NULL REFERENCES dg_categories(category_id),
  brand VARCHAR(80),
  unit_price NUMERIC(12,2) NOT NULL,
  cost_price NUMERIC(12,2),
  weight_kg NUMERIC(8,3),
  dimensions VARCHAR(60),
  color VARCHAR(40),
  size VARCHAR(20),
  material VARCHAR(60),
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  created_at DATE NOT NULL DEFAULT CURRENT_DATE,
  discontinued_date DATE,
  supplier_name VARCHAR(120),
  warranty_months INTEGER DEFAULT 12
);

CREATE TABLE IF NOT EXISTS dg_orders (
  order_id SERIAL PRIMARY KEY,
  customer_id INTEGER NOT NULL REFERENCES dg_customers(customer_id),
  order_date DATE NOT NULL,
  required_date DATE,
  shipped_date DATE,
  ship_country VARCHAR(80),
  ship_state VARCHAR(80),
  ship_city VARCHAR(100),
  ship_postal VARCHAR(20),
  ship_address VARCHAR(200),
  status VARCHAR(30) NOT NULL DEFAULT 'pending',
  payment_method VARCHAR(40),
  shipping_method VARCHAR(40),
  subtotal NUMERIC(12,2) NOT NULL DEFAULT 0,
  tax_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
  shipping_cost NUMERIC(12,2) NOT NULL DEFAULT 0,
  discount_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
  total_amount NUMERIC(12,2) NOT NULL DEFAULT 0,
  currency VARCHAR(10) DEFAULT 'USD',
  notes TEXT
);

CREATE TABLE IF NOT EXISTS dg_order_items (
  order_item_id SERIAL PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES dg_orders(order_id) ON DELETE CASCADE,
  product_id INTEGER NOT NULL REFERENCES dg_products(product_id),
  quantity INTEGER NOT NULL CHECK (quantity > 0),
  unit_price NUMERIC(12,2) NOT NULL,
  discount_pct NUMERIC(5,4) NOT NULL DEFAULT 0,
  tax_pct NUMERIC(5,4) NOT NULL DEFAULT 0,
  line_total NUMERIC(12,2) NOT NULL DEFAULT 0,
  returned_quantity INTEGER NOT NULL DEFAULT 0,
  return_reason VARCHAR(120),
  fulfillment_status VARCHAR(30) DEFAULT 'fulfilled',
  warehouse_code VARCHAR(20),
  serial_number VARCHAR(80),
  gift_wrap BOOLEAN DEFAULT FALSE,
  notes TEXT,
  created_at DATE DEFAULT CURRENT_DATE
);

CREATE TABLE IF NOT EXISTS dg_payments (
  payment_id SERIAL PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES dg_orders(order_id),
  customer_id INTEGER NOT NULL REFERENCES dg_customers(customer_id),
  payment_date DATE NOT NULL,
  amount NUMERIC(12,2) NOT NULL,
  currency VARCHAR(10) DEFAULT 'USD',
  payment_method VARCHAR(40),
  transaction_id VARCHAR(120) UNIQUE,
  status VARCHAR(30) NOT NULL DEFAULT 'succeeded',
  gateway VARCHAR(60),
  card_last4 VARCHAR(4),
  billing_country VARCHAR(80),
  billing_city VARCHAR(100),
  failure_reason VARCHAR(200),
  refunded_amount NUMERIC(12,2) DEFAULT 0,
  processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dg_product_reviews (
  review_id SERIAL PRIMARY KEY,
  product_id INTEGER NOT NULL REFERENCES dg_products(product_id),
  customer_id INTEGER NOT NULL REFERENCES dg_customers(customer_id),
  order_id INTEGER REFERENCES dg_orders(order_id),
  rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
  title VARCHAR(200),
  body TEXT,
  review_date DATE NOT NULL,
  helpful_votes INTEGER DEFAULT 0,
  verified_purchase BOOLEAN DEFAULT TRUE,
  sentiment VARCHAR(20),
  language VARCHAR(10) DEFAULT 'en',
  source VARCHAR(40) DEFAULT 'web',
  is_approved BOOLEAN DEFAULT TRUE,
  response_text TEXT,
  response_date DATE
);

CREATE INDEX IF NOT EXISTS idx_orders_customer ON dg_orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_date ON dg_orders(order_date);
CREATE INDEX IF NOT EXISTS idx_orders_status ON dg_orders(status);
CREATE INDEX IF NOT EXISTS idx_items_order ON dg_order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_items_product ON dg_order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_products_category ON dg_products(category_id);
CREATE INDEX IF NOT EXISTS idx_payments_order ON dg_payments(order_id);
CREATE INDEX IF NOT EXISTS idx_reviews_product ON dg_product_reviews(product_id);
