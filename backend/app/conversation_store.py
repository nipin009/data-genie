"""Database-backed conversation memory and dashboard audit log.

Operational tables use the ``datagenie_`` prefix, rather than ``dg_``. They
live in the same database but are excluded from Text-to-SQL retrieval.
"""
from datetime import datetime, timezone
import json
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy import inspect, text

from .db import get_engine
from .logging_config import log

_ready_engines: set[str] = set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_tables() -> None:
    """Create local-dev tables; production Compose creates them during DB init."""
    engine = get_engine()
    key = str(engine.url)
    if key in _ready_engines:
        return
    ddl = [
        """CREATE TABLE IF NOT EXISTS datagenie_sessions (
            conversation_id VARCHAR(80) PRIMARY KEY,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            pending_clarification TEXT NOT NULL DEFAULT '{}'
        )""",
        """CREATE TABLE IF NOT EXISTS datagenie_messages (
            message_id VARCHAR(40) PRIMARY KEY,
            conversation_id VARCHAR(80) NOT NULL REFERENCES datagenie_sessions(conversation_id) ON DELETE CASCADE,
            role VARCHAR(20) NOT NULL, content TEXT NOT NULL, metadata TEXT, created_at TIMESTAMP NOT NULL
        )""",
        """CREATE TABLE IF NOT EXISTS datagenie_request_logs (
            log_id VARCHAR(40) PRIMARY KEY, conversation_id VARCHAR(80), request_text TEXT NOT NULL,
            classification VARCHAR(40), sql_text TEXT, selected_tables TEXT, row_count INTEGER,
            latency_ms INTEGER, status VARCHAR(20) NOT NULL, error_text TEXT, created_at TIMESTAMP NOT NULL
        )""",
        "CREATE INDEX IF NOT EXISTS idx_datagenie_messages_session ON datagenie_messages(conversation_id, created_at)",
        "CREATE INDEX IF NOT EXISTS idx_datagenie_logs_created ON datagenie_request_logs(created_at)",
    ]
    try:
        with engine.begin() as conn:
            for statement in ddl:
                conn.execute(text(statement))
        # Existing local databases from before metadata support need a small,
        # non-destructive migration. Fresh Compose databases get this column
        # from 03_memory.sql.
        columns = {c["name"] for c in inspect(engine).get_columns("datagenie_messages")}
        if "metadata" not in columns:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE datagenie_messages ADD COLUMN metadata TEXT"))
        _ready_engines.add(key)
    except Exception as exc:
        # The restricted production role cannot issue DDL. Compose creates the
        # tables through backend/data/init/03_memory.sql before the API starts.
        log.debug("operational table DDL skipped: %s", exc)
        _ready_engines.add(key)


def get_or_create(cid: Optional[str]) -> str:
    ensure_tables()
    nid = cid or f"conv-{uuid.uuid4().hex[:12]}"
    with get_engine().begin() as conn:
        found = conn.execute(text("SELECT conversation_id FROM datagenie_sessions WHERE conversation_id = :cid"), {"cid": nid}).first()
        if not found:
            now = _now()
            conn.execute(text("""INSERT INTO datagenie_sessions
                (conversation_id, created_at, updated_at, pending_clarification)
                VALUES (:cid, :created, :updated, :pending)"""),
                {"cid": nid, "created": now, "updated": now, "pending": "{}"})
    return nid


def append(cid: str, role: str, content: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    get_or_create(cid)
    now = _now()
    with get_engine().begin() as conn:
        conn.execute(text("""INSERT INTO datagenie_messages
            (message_id, conversation_id, role, content, metadata, created_at)
            VALUES (:id, :cid, :role, :content, :metadata, :created)"""),
            {"id": uuid.uuid4().hex, "cid": cid, "role": role, "content": content,
             "metadata": json.dumps(metadata) if metadata else None, "created": now})
        conn.execute(text("UPDATE datagenie_sessions SET updated_at = :updated WHERE conversation_id = :cid"),
                     {"updated": now, "cid": cid})


def history(cid: str, limit: int = 50) -> List[Dict[str, Any]]:
    ensure_tables()
    with get_engine().connect() as conn:
        rows = conn.execute(text("""SELECT role, content, metadata FROM datagenie_messages
            WHERE conversation_id = :cid ORDER BY created_at DESC LIMIT :limit"""),
            {"cid": cid, "limit": limit}).mappings().all()
    messages = []
    for row in reversed(rows):
        try:
            metadata = json.loads(row["metadata"]) if row["metadata"] else None
        except (TypeError, json.JSONDecodeError):
            metadata = None
        messages.append({"role": row["role"], "content": row["content"], "metadata": metadata})
    return messages


def set_pending(
    cid: str,
    questions: List[str],
    original_question: str = "",
    query_spec: Optional[Dict] = None,
    clarification_context: str = "",
) -> None:
    get_or_create(cid)
    pending = {
        "questions": questions,
        "original_question": original_question,
        "query_spec": query_spec or {},
        "clarification_context": clarification_context,
    }
    with get_engine().begin() as conn:
        conn.execute(text("""UPDATE datagenie_sessions
            SET pending_clarification = :pending, updated_at = :updated WHERE conversation_id = :cid"""),
            {"pending": json.dumps(pending), "updated": _now(), "cid": cid})


def pop_pending(cid: str) -> Dict[str, Any]:
    ensure_tables()
    empty: Dict[str, Any] = {"questions": [], "original_question": "", "query_spec": {}, "clarification_context": ""}
    with get_engine().begin() as conn:
        raw = conn.execute(text("SELECT pending_clarification FROM datagenie_sessions WHERE conversation_id = :cid"),
                           {"cid": cid}).scalar()
        conn.execute(text("UPDATE datagenie_sessions SET pending_clarification = :pending, updated_at = :updated WHERE conversation_id = :cid"),
                     {"pending": "{}", "updated": _now(), "cid": cid})
    try:
        return {**empty, **json.loads(raw or "{}")}
    except (TypeError, json.JSONDecodeError):
        return empty


def log_request(conversation_id: str, request_text: str, result: Optional[Dict[str, Any]], latency_ms: int,
                error: Optional[str] = None) -> None:
    ensure_tables()
    result = result or {}
    with get_engine().begin() as conn:
        conn.execute(text("""INSERT INTO datagenie_request_logs
            (log_id, conversation_id, request_text, classification, sql_text, selected_tables,
             row_count, latency_ms, status, error_text, created_at)
            VALUES (:id, :cid, :request, :classification, :sql, :tables, :rows, :latency, :status, :error, :created)"""),
            {"id": uuid.uuid4().hex, "cid": conversation_id, "request": request_text,
             "classification": result.get("classification"), "sql": result.get("sql"),
             "tables": json.dumps(result.get("selected_tables") or []), "rows": result.get("row_count", 0),
             "latency": latency_ms, "status": "error" if error else "ok", "error": error, "created": _now()})


def dashboard_sessions(limit: int = 50) -> List[Dict[str, Any]]:
    ensure_tables()
    with get_engine().connect() as conn:
        rows = conn.execute(text("""SELECT s.conversation_id, s.created_at, s.updated_at, COUNT(m.message_id) AS message_count
            FROM datagenie_sessions s LEFT JOIN datagenie_messages m ON m.conversation_id = s.conversation_id
            GROUP BY s.conversation_id, s.created_at, s.updated_at ORDER BY s.updated_at DESC LIMIT :limit"""),
            {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def dashboard_logs(limit: int = 100) -> List[Dict[str, Any]]:
    ensure_tables()
    with get_engine().connect() as conn:
        rows = conn.execute(text("""SELECT log_id, conversation_id, request_text, classification, row_count,
            latency_ms, status, error_text, created_at FROM datagenie_request_logs
            ORDER BY created_at DESC LIMIT :limit"""), {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]


def summarize_request_logs(logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return portable, privacy-safe operational aggregates for the dashboard.

    Aggregation deliberately happens in Python rather than using database-specific
    percentile functions, so local SQLite and production Postgres report the same
    values.  Only audit metadata is used; request text and generated SQL are not
    exposed in this summary.
    """
    total = len(logs)
    successful = sum(1 for item in logs if item.get("status") == "ok")
    failed = total - successful
    latency = sorted(int(item["latency_ms"]) for item in logs if item.get("latency_ms") is not None)
    # Nearest-rank p95 keeps the metric intuitive for small windows as well.
    p95 = latency[max(0, (95 * len(latency) + 99) // 100 - 1)] if latency else None
    classifications: Dict[str, int] = {}
    for item in logs:
        label = item.get("classification") or "unknown"
        classifications[label] = classifications.get(label, 0) + 1
    return {
        "window_requests": total,
        "successful_requests": successful,
        "failed_requests": failed,
        "failure_rate": round(failed / total, 4) if total else 0.0,
        "avg_latency_ms": round(sum(latency) / len(latency), 1) if latency else None,
        "p95_latency_ms": p95,
        "classification_counts": dict(sorted(classifications.items())),
    }


def dashboard_metrics(limit: int = 1000) -> Dict[str, Any]:
    """Summarize the most recent audit records for operational monitoring."""
    ensure_tables()
    with get_engine().connect() as conn:
        rows = conn.execute(text("""SELECT classification, latency_ms, status
            FROM datagenie_request_logs ORDER BY created_at DESC LIMIT :limit"""),
            {"limit": limit}).mappings().all()
    metrics = summarize_request_logs([dict(row) for row in rows])
    metrics["window_size"] = limit
    return metrics


def clear_all() -> None:
    ensure_tables()
    with get_engine().begin() as conn:
        conn.execute(text("DELETE FROM datagenie_request_logs"))
        conn.execute(text("DELETE FROM datagenie_messages"))
        conn.execute(text("DELETE FROM datagenie_sessions"))
