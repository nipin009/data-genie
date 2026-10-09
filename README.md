# Data Genie — Production Text-to-SQL

Chat-based Text-to-SQL over the local Postgres database **`local_db`**: 23 commerce and operations tables with the `dg_` prefix, including orders, customers, products, payments, inventory, suppliers, campaigns, support tickets, and subscriptions. FastAPI + LangGraph + Gemini + SQLAlchemy + SQLGlot backend; Next.js + TypeScript + Tailwind + Recharts frontend. The app scopes itself to `dg_*` tables; other tables in `local_db` (e.g. `daily_hustle_*`) are never queried.

## Architecture

```
User → Next.js chat UI → POST /api/chat ─┐
                                         ▼
                    LangGraph: classify → retrieve → generate → validate ⇄ repair (≤2) → execute → answer+visualize
                                         │              │           │           │
                                    ambiguous→clarify  schema+FK   Gemini/     SQLGlot SELECT-only,
                                    unsupported/        join graph fallback    known tables/cols,
                                    unrelated→polite    +metrics   SQL         LIMIT, timeout
```

- **Before SQL**: every request classified as `in_scope | ambiguous | unsupported | unrelated`. Ambiguous → targeted follow-up questions via clarification cards; conversation state preserved; no guessing, no execution until resolved. Unrelated → polite redirect, no DB hit. Unsupported (writes/DDL, forecasting) → clear explanation.
- **Schema-aware**: live SQLAlchemy reflection (`schema_introspection.py`), FK join graph + BFS path, business metrics layer (`metrics.py`), keyword+metric retrieval with 1-hop FK expansion (`schema_retrieval.py`).
- **Secure execution**: SQLGlot single-SELECT enforcement, strict SQL-function allowlist, known-table/column check, semantic requirement checks, LIMIT clamp (≤500), Postgres `statement_timeout` + read-only transaction, row cap + truncation flag.
- **Semantic planning**: every in-scope request is converted to a typed QuerySpec (metrics, dimensions, filters, required outputs and ranking). With Gemini configured, structured planning broadens coverage beyond templates; safe live-value linking binds phrases such as category, product, country, or status values to inspected columns. Relative dates such as "last month" are resolved deterministically. SQL which omits a bound requirement is repaired or declined.
- **Grounded answers**: `answer.py` / Gemini summarizer only uses returned rows; empty results get an honest "no matching data" message.
- **Auto charts**: deterministic `visualization.py` (line for time series, bar for categories, pie for small shares, table otherwise) with reason string; UI offers chart/table switch, CSV export, filter/sort/pagination.
- **Observability**: structured logging, persistent request audit records, and an admin metrics summary (request count, failure rate, average/p95 latency, and workflow classifications).

## Quickstart (Postgres local_db, no Docker)

Prereqs: Python 3.11+, Node 18+, local Postgres running with a `local_db` database (this machine: Homebrew Postgres, socket auth as `nipinmishra`).

```bash
# 1. Backend
cd backend
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example ../.env   # defaults already point at Postgres local_db; just add GOOGLE_API_KEY optionally
export DATABASE_URL="postgresql+psycopg2://nipinmishra@/local_db?host=/tmp" TABLE_PREFIX="dg_"
python -m scripts.seed_db --rows-scale 1.0   # (re)creates dg_* tables in local_db (leaves other tables alone)
uvicorn app.main:app --reload --port 8001

# 2. Frontend (new terminal)
cd frontend
npm install
echo "NEXT_PUBLIC_API_BASE=http://localhost:8001" > .env.local
npm run dev   # http://localhost:3000
```

Without `GOOGLE_API_KEY`, the copied development `.env` enables a limited deterministic fallback for the supported demo templates. It declines unsupported requests rather than substituting a plausible query. Configure Gemini for general Text-to-SQL, and keep the fallback disabled in production if generic LLM-backed querying is required.

## Docker

```bash
cp .env.example .env   # set GOOGLE_API_KEY etc.
docker compose up --build
# frontend http://localhost:3000, backend http://localhost:8001
# seed (uses the privileged developer utility, never the API role):
# docker compose run --rm seed
```

Compose initializes the API with the restricted `datagenie_app` role. If you already have a `pgdata` volume, Postgres will not re-run initialization files; create/grant the role once without deleting data:

```bash
docker compose exec -T db psql -U datagenie -d datagenie -f /docker-entrypoint-initdb.d/01_app_role.sql
docker compose exec -T db psql -U datagenie -d datagenie -f /docker-entrypoint-initdb.d/03_memory.sql
```

`docker-compose.yml` runs Postgres 16 + backend + frontend. `DATABASE_URL` inside compose points at the `db` service.

## API

- `POST /api/chat` `{message, conversation_id?}` → full `ChatResponse` (classification, answer, sql, columns/rows, chart, clarification_questions…)
- `POST /api/chat/stream` SSE events `status` → `final` (same payload)
- `POST /api/clarify` `{conversation_id, answers}` → re-runs workflow with merged context
- `GET /api/history/{id}`, `GET /api/schema`, `GET /healthz`
- `GET /api/dashboard/sessions`, `GET /api/dashboard/logs`, `GET /api/dashboard/metrics` → persistent memory, request audit data, and operational monitoring shown in the admin dashboard
- `POST /api/admin/mutations/preview` → admin-only proposal for one `INSERT`, `UPDATE`, `DELETE`, `CREATE TABLE`, `ALTER TABLE`, or `DROP TABLE`; does not execute SQL
- `POST /api/admin/mutations/confirm` → applies that exact short-lived proposal only after `confirmation: "APPLY"`

## Tests & benchmark (local_db)

```bash
cd backend
export DATABASE_URL="postgresql+psycopg2://nipinmishra@/local_db?host=/tmp" TABLE_PREFIX="dg_"
python -m pytest -q                                   # 34 tests, all offline-safe
python -m scripts.run_benchmark --output benchmark_results.json
# Fully self-contained local/CI benchmark (no running Postgres required):
python -m scripts.run_benchmark --temporary-sqlite --output benchmark_results.json
```

Benchmark `benchmark/questions.yaml` (18 questions): joins, aggregations, edge cases (empty result, failed payments, return rate), ambiguity (must clarify, no SQL), unsupported (DELETE, forecast), irrelevant (joke, capital). It reports classification, row behaviour, and a required-SQL contract; it is a regression suite, not a claim of universal natural-language accuracy.

## Config (env)

| Var | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg2://nipinmishra@/local_db?host=/tmp` | local Postgres `local_db` (socket auth); TCP form `postgresql+psycopg2://USER:PASS@localhost:5432/local_db` also works |
| `TABLE_PREFIX` | `dg_` | Physical table prefix; all tables/queries use it |
| `GOOGLE_API_KEY` | — | Enables Gemini; offline fallback otherwise |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | Model name |
| `QUERY_TIMEOUT_MS` / `MAX_ROWS` / `MAX_REPAIR_RETRIES` | 15000 / 500 / 2 | Guardrails |
| `MAX_QUERY_COST` / `LLM_SUMMARIZER` | 0 / false | Optional Postgres planner-cost cap / optional second LLM prose call |
| `AUTH_ENABLED` / `API_KEYS` | false / — | Optional API-key RBAC; keys use `secret:analyst` or `secret:admin` |

For production, set `AUTH_ENABLED=true` and issue separate long random keys for
the `analyst` (chat) and `admin` (dashboard) roles. Send each key in
`X-API-Key`. The browser key setting is only suitable for an internal demo;
put public-facing authentication at a server-side gateway or SSO proxy.

Mutations are disabled by default. To use the human-reviewed admin mutation
workflow, set both `AUTH_ENABLED=true` and `ENABLE_MUTATIONS=true`, configure
an `admin` API key, inspect the preview response, then send its `proposal_id`
to the confirm endpoint with `confirmation` exactly equal to `APPLY`.
| `FRONTEND_ORIGIN` | http://localhost:3000 | CORS |

## Layout

```
backend/app/{main,graph,classifier,schema_introspection,schema_retrieval,metrics,llm,fallback_sql,sql_validation,db,visualization,answer,conversation_store,config,tables,schemas,logging_config}.py
backend/{local_db/README.md (connection notes),data/schema.sql,scripts/{seed_db,run_benchmark}.py,benchmark/questions.yaml,benchmark_results.json,tests/test_*.py}
frontend/{app/{page,layout,globals.css},components/{ChatMessage,ClarificationCard,SqlPreview,QueryDetails,ChartView,DataTable}.tsx,lib/{api,types}.ts}
```
