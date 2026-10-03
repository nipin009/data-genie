"""Secure, configurable database access.

- Connection string comes from env (DATABASE_URL), never hardcoded schema.
- Read-only execution: validation layer enforces SELECT-only; here we additionally
  set Postgres statement_timeout + read-only transaction, and cap rows.
- Works with PostgreSQL (production) and SQLite (local dev / tests).
"""
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional, Sequence

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import get_settings
from .logging_config import log

_engine: Optional[Engine] = None


def get_engine(url: Optional[str] = None) -> Engine:
    global _engine
    settings = get_settings()
    db_url = url or settings.DATABASE_URL
    if _engine is None:
        connect_args: Dict[str, Any] = {}
        if db_url.startswith("sqlite"):
            connect_args = {"check_same_thread": False}
            # Ensure local_db directory exists for file-backed SQLite stores.
            try:
                import os as _os
                _path = db_url.split("sqlite:///", 1)[-1].split("?")[0]
                if _path and _path != ":memory:":
                    _dir = _os.path.dirname(_os.path.abspath(_path))
                    if _dir and ("local_db" in _path or _path.endswith(".db")):
                        _os.makedirs(_dir, exist_ok=True)
            except Exception:
                pass
        _engine = create_engine(
            db_url, pool_pre_ping=True, connect_args=connect_args, future=True,
            pool_size=settings.DB_POOL_SIZE, max_overflow=settings.DB_MAX_OVERFLOW,
        )
        log.info("DB engine created for %s", _redact(db_url))
    return _engine


def reset_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def _redact(url: str) -> str:
    # Avoid logging passwords.
    if "@" in url and "://" in url:
        try:
            prefix, rest = url.split("://", 1)
            if "@" in rest:
                _, hostpart = rest.rsplit("@", 1)
                return f"{prefix}://***@{hostpart}"
        except Exception:
            pass
    return url


def is_postgres(engine: Engine) -> bool:
    return engine.dialect.name == "postgresql"


@contextmanager
def readonly_session(engine: Optional[Engine] = None) -> Iterator[Any]:
    eng = engine or get_engine()
    with eng.connect() as conn:
        with conn.begin():
            if is_postgres(eng):
                settings = get_settings()
                # SET TRANSACTION must be the first command in the transaction.
                conn.execute(text("SET TRANSACTION READ ONLY"))
                conn.execute(text(f"SET LOCAL statement_timeout = {int(settings.QUERY_TIMEOUT_MS)}"))
                conn.execute(text(f"SET LOCAL lock_timeout = {int(settings.LOCK_TIMEOUT_MS)}"))
            elif eng.dialect.name == "sqlite":
                conn.execute(text("PRAGMA query_only = ON"))
            try:
                yield conn
            finally:
                # query_only is connection-scoped in SQLite; reset it before
                # returning a pooled connection that persistence may need.
                if eng.dialect.name == "sqlite":
                    conn.execute(text("PRAGMA query_only = OFF"))


def query_cost(sql: str, engine: Optional[Engine] = None) -> Optional[float]:
    """Return PostgreSQL planner total cost, or None for other dialects."""
    eng = engine or get_engine()
    if not is_postgres(eng):
        return None
    with readonly_session(eng) as conn:
        plan = conn.execute(text("EXPLAIN (FORMAT JSON) " + sql)).scalar()
    try:
        return float(plan[0]["Plan"]["Total Cost"])
    except (TypeError, KeyError, IndexError, ValueError):
        return None


def execute_readonly_sql(
    sql: str,
    params: Optional[Dict[str, Any]] = None,
    engine: Optional[Engine] = None,
    max_rows: Optional[int] = None,
) -> Dict[str, Any]:
    """Execute a validated SELECT and return columns + rows (list of dicts)."""
    settings = get_settings()
    limit = max_rows or settings.MAX_ROWS
    eng = engine or get_engine()
    params = params or {}
    with readonly_session(eng) as conn:
        # SQLite has no statement_timeout; rely on validation + LIMIT.
        result = conn.execute(text(sql), params)
        cols: List[str] = list(result.keys())
        raw = result.fetchmany(limit + 1)
        truncated = len(raw) > limit
        rows_raw = raw[:limit]
        rows: List[Dict[str, Any]] = []
        for r in rows_raw:
            # SQLAlchemy 2.0 Row -> mapping
            try:
                rows.append(dict(r._mapping))
            except Exception:
                rows.append({c: v for c, v in zip(cols, r)})
        # JSON-safe: stringify non-primitive types
        safe_rows = [_json_safe_row(r) for r in rows]
        return {"columns": cols, "rows": safe_rows, "row_count": len(safe_rows), "truncated": truncated}


def _json_safe_row(row: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in row.items():
        if v is None or isinstance(v, (str, int, float, bool)):
            out[k] = v
        else:
            # dates, Decimals, UUIDs -> str
            try:
                import datetime, decimal
                if isinstance(v, (datetime.date, datetime.datetime, datetime.time)):
                    out[k] = v.isoformat()
                elif isinstance(v, decimal.Decimal):
                    out[k] = float(v)
                else:
                    out[k] = str(v)
            except Exception:
                out[k] = str(v)
    return out
