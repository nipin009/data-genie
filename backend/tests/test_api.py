"""Integration tests: full LangGraph workflow + API on local_db (SQLite, seeded, no LLM key)."""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["GOOGLE_API_KEY"] = ""
os.environ["TABLE_PREFIX"] = "dg_"


@pytest.fixture(scope="module")
def seeded(tmp_path_factory):
    dbdir = tmp_path_factory.mktemp("local_db")
    dbpath = str(dbdir / "datagenie.db")
    os.environ["DATABASE_URL"] = f"sqlite:///{dbpath}"
    import app.db as dbmod
    import app.graph as gmod
    dbmod.reset_engine()
    gmod.reset_schema_cache()
    from app.config import get_settings
    get_settings.cache_clear() if hasattr(get_settings, "cache_clear") else None
    try:
        from app.config import get_settings as gs
        if hasattr(gs, "cache_clear"):
            gs.cache_clear()
    except Exception:
        pass
    from scripts.seed_db import run
    run(scale=0.15, db_url=f"sqlite:///{dbpath}")
    gmod.reset_schema_cache()
    yield dbpath


@pytest.fixture()
def client(seeded):
    from app.main import app
    return TestClient(app)


def test_unrelated_no_sql(client):
    r = client.post("/api/chat", json={"message": "Tell me a joke about pirates"})
    assert r.status_code == 200
    body = r.json()
    assert body["classification"] == "unrelated"
    assert body["rows"] == [] and body["sql"] is None


def test_health_reports_runtime_query_capability(client):
    health = client.get("/healthz")
    assert health.status_code == 200
    assert "llm_configured" in health.json()
    assert "offline_fallback_enabled" in health.json()
    assert client.get("/readyz").status_code == 200


def test_greeting_and_data_genie_questions_are_answered_without_sql(client):
    greeting = client.post("/api/chat", json={"message": "hello"}).json()
    assert greeting["classification"] == "assistant_info"
    assert greeting["sql"] is None and "data genie" in greeting["answer"].lower()
    help_response = client.post("/api/chat", json={"message": "How does this app work?"}).json()
    assert help_response["classification"] == "assistant_info"
    assert help_response["sql"] is None and "read-only" in help_response["answer"].lower()


def test_ambiguous_asks_questions(client):
    r = client.post("/api/chat", json={"message": "Show me recent sales"})
    body = r.json()
    assert body["classification"] == "ambiguous"
    assert len(body["clarification_questions"]) > 0
    assert body["rows"] == []


def test_unsupported_blocked(client):
    r = client.post("/api/chat", json={"message": "Delete all cancelled orders"})
    assert r.json()["classification"] == "unsupported"


def test_schema_requests_bypass_sql(client):
    r = client.post("/api/chat", json={"message": "Give the table anmes only"})
    body = r.json()
    assert body["classification"] == "schema_request"
    assert body["sql"] is None and body["rows"] == []
    assert "dg_orders" in body["answer"]
    assert "order_date" not in body["answer"]

    count = client.post("/api/chat", json={"message": "How many tables are there in the database?"}).json()
    assert count["classification"] == "schema_request"
    assert "23 tables" in count["answer"]

    full_schema = client.post("/api/chat", json={"message": "Give the schema of each table which you have"}).json()
    assert full_schema["classification"] == "schema_request"
    assert full_schema["sql"] is None
    assert "dg_orders:" in full_schema["answer"] and "order_date" in full_schema["answer"]


def test_history_and_dashboard_are_persisted(client):
    chat = client.post("/api/chat", json={"message": "Give table names only"}).json()
    cid = chat["conversation_id"]
    history = client.get(f"/api/history/{cid}").json()
    assert [m["role"] for m in history["messages"]] == ["user", "assistant"]
    assert history["messages"][1]["metadata"]["classification"] == "schema_request"

    sessions = client.get("/api/dashboard/sessions").json()["sessions"]
    assert any(s["conversation_id"] == cid for s in sessions)
    logs = client.get("/api/dashboard/logs").json()["logs"]
    assert any(l["conversation_id"] == cid and l["status"] == "ok" for l in logs)


def test_in_scope_executes_grounded(client):
    r = client.post("/api/chat", json={"message": "What was total revenue and order count in 2024?"})
    body = r.json()
    assert body["classification"] == "in_scope", body
    assert body["sql"] and "SELECT" in body["sql"].upper()
    assert "dg_" in body["sql"]
    assert body["row_count"] >= 1
    assert "999999999" not in body["answer"]


def test_join_query(client):
    r = client.post("/api/chat", json={"message": "Total revenue by product category, ordered by revenue descending"})
    body = r.json()
    assert body["classification"] == "in_scope"
    assert body["row_count"] >= 1
    assert body["chart"]["type"] in ("bar", "pie", "table", "line")


def test_clarify_flow(client):
    r1 = client.post("/api/chat", json={"message": "Who are the top customers?"})
    cid = r1.json()["conversation_id"]
    assert r1.json()["classification"] == "ambiguous"
    r2 = client.post("/api/clarify", json={"conversation_id": cid, "answers": "Top 5 by lifetime spend in 2024"})
    body = r2.json()
    assert body["classification"] == "in_scope"
    assert body["row_count"] >= 1


def test_clarification_context_does_not_recursively_wrap_original_request():
    from app.main import _clarification_prompt
    combined = _clarification_prompt("Revenue by category", ["Which year?"], "net of returns", "last year")
    assert combined.count("Original request:") == 1
    assert "Earlier clarification: net of returns" in combined
    assert "User clarification: last year" in combined


def test_sql_injection_blocked():
    from app.sql_validation import validate_sql
    known = {"dg_orders": {"order_id"}}
    assert not validate_sql("SELECT order_id FROM dg_orders; DROP TABLE dg_orders", known).ok


def test_optional_api_key_rbac(client, monkeypatch):
    monkeypatch.setenv("AUTH_ENABLED", "true")
    monkeypatch.setenv("API_KEYS", "analyst-secret:analyst,admin-secret:admin")
    from app.config import get_settings
    get_settings.cache_clear()
    try:
        assert client.get("/healthz").status_code == 200
        assert client.post("/api/chat", json={"message": "Give table names only"}).status_code == 401
        assert client.post("/api/chat", headers={"X-API-Key": "analyst-secret"}, json={"message": "Give table names only"}).status_code == 200
        assert client.get("/api/dashboard/logs", headers={"X-API-Key": "analyst-secret"}).status_code == 403
        assert client.get("/api/dashboard/logs", headers={"X-API-Key": "admin-secret"}).status_code == 200
    finally:
        monkeypatch.setenv("AUTH_ENABLED", "false")
        monkeypatch.delenv("API_KEYS", raising=False)
        get_settings.cache_clear()
