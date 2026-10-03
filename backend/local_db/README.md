# local_db — Postgres database (the ONLY store this project uses).

- Database: `local_db` on the local Postgres server (Homebrew, socket auth).
- Connection: `DATABASE_URL=postgresql+psycopg2://nipinmishra@/local_db?host=/tmp`
- Tables (all `dg_` prefixed, owned by this project): `dg_categories`,
  `dg_customers`, `dg_products`, `dg_orders`, `dg_order_items`, `dg_payments`,
  `dg_product_reviews`
- Other tables in `local_db` (e.g. `daily_hustle_*`) belong to other projects:
  the app filters its schema snapshot to `TABLE_PREFIX` (`dg_`) and never queries them.
- Rebuild: `python -m scripts.seed_db --rows-scale 1.0` (only touches `dg_*`).
