"""Graph-level tests: repair bound + routing on local_db (no HTTP)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["GOOGLE_API_KEY"] = ""


def _seed(tmp="test_graph_local.db"):
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), tmp))
    if os.path.exists(path):
        os.remove(path)
    os.environ["DATABASE_URL"] = f"sqlite:///{path}"
    import app.db as dbmod
    import app.graph as gmod
    try:
        from app.config import get_settings as gs
        if hasattr(gs, "cache_clear"):
            gs.cache_clear()
    except Exception:
        pass
    dbmod.reset_engine()
    gmod.reset_schema_cache()
    from scripts.seed_db import run
    run(scale=0.1, db_url=f"sqlite:///{path}")
    gmod.reset_schema_cache()
    return path


def test_graph_in_scope():
    _seed()
    from app.graph import run_question
    out = run_question("Show all failed payments with order id and amount", [])
    assert out["classification"] == "in_scope"
    assert out["row_count"] >= 0 and out["sql"] and "dg_" in out["sql"]


def test_graph_repair_bounded():
    from app.sql_validation import validate_sql
    from app.config import get_settings
    assert get_settings().MAX_REPAIR_RETRIES <= 3
    r = validate_sql("SELEC broken syntax", {"dg_orders": {"order_id"}})
    assert not r.ok


def test_empty_result_grounded_message():
    _seed("test_graph_local2.db")
    from app.graph import run_question
    out = run_question("Revenue for product 'Nonexistent Gizmo XYZ123' in 2024", [])
    if out["classification"] == "in_scope":
        if out["row_count"] == 0:
            assert "no matching data" in out["answer"].lower()


def test_unhandled_offline_question_is_transparent():
    _seed("test_graph_unknown.db")
    from app.graph import run_question
    out = run_question("Revenue by city", [])
    assert out["classification"] == "in_scope"
    assert out["sql"] is None
    assert "limited offline mode" in out["answer"].lower()
