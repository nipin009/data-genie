"""Maintained Google GenAI client for planning, SQL generation, and repair."""
import re
from typing import Any, List, Optional, Type, TypeVar

from pydantic import BaseModel

from .config import get_settings
from .logging_config import log

ModelT = TypeVar("ModelT", bound=BaseModel)


def has_llm_key() -> bool:
    return bool(get_settings().GOOGLE_API_KEY)


def has_llm_runtime() -> bool:
    """True only when credentials and the maintained Gemini SDK are present."""
    if not has_llm_key():
        return False
    try:
        from google import genai  # noqa: F401
        return True
    except ImportError:
        return False


def _client():
    from google import genai
    return genai.Client(api_key=get_settings().GOOGLE_API_KEY)


def _interaction(prompt: str, response_schema: Optional[dict] = None) -> str:
    """Run one stateless Gemini interaction and return only final text."""
    from google.genai import types

    settings = get_settings()
    # Keep a strong reference for the entire request.  Chaining
    # ``_client().interactions.create(...)`` lets the short-lived Client be
    # garbage-collected (and closed) before the SDK sends its HTTP request.
    client = _client()
    kwargs: dict[str, Any] = {"model": settings.GEMINI_MODEL, "input": prompt, "store": False}
    if response_schema:
        kwargs["response_format"] = {
            "type": "text", "mime_type": "application/json", "schema": response_schema,
        }
    try:
        interaction = client.interactions.create(**kwargs)
        return str(getattr(interaction, "output_text", "") or "").strip()
    except TypeError:
        # Compatibility for early maintained SDK releases. This path still
        # never imports the retired google.generativeai package.
        config: dict[str, Any] = {"temperature": 0.1}
        if response_schema:
            config.update({"response_mime_type": "application/json", "response_schema": response_schema})
        response = client.models.generate_content(
            model=settings.GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(**config),
        )
        return str(getattr(response, "text", "") or "").strip()
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()


def generate_structured(prompt: str, schema: Type[ModelT]) -> ModelT:
    """Generate and validate a typed model before it can affect SQL."""
    raw = _interaction(prompt, schema.model_json_schema())
    if not raw:
        raise RuntimeError("Gemini returned no structured output")
    return schema.model_validate_json(raw)


def _clean_sql(text: str) -> str:
    if "```" in text:
        match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
        if match:
            return match.group(1).strip()
    return text.strip()


def generate_sql_with_llm(question: str, schema_context: str, history: Optional[List[dict]] = None) -> str:
    """Generate SQL only from an already verified plan and schema context."""
    if not has_llm_runtime():
        if get_settings().ALLOW_DETERMINISTIC_FALLBACK:
            from .fallback_sql import build_fallback_sql
            return build_fallback_sql(question, schema_context)
        return ""
    settings = get_settings()
    dialect = "SQLite" if settings.DATABASE_URL.startswith("sqlite") else "PostgreSQL"
    history_text = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in (history or [])[-6:])
    prompt = f"""Generate exactly one valid {dialect} SELECT statement and no explanation.

The QUERY REQUIREMENTS and LIVE VALUE RESOLUTION are mandatory. Preserve every
resolved table, column, value, and date bound exactly. Use only supplied schema
objects and joins, an explicit LIMIT of at most 500, and no writes or DDL.

Schema and verified plan:
{schema_context}

Recent conversation:
{history_text}

Question: {question}
SQL:"""
    try:
        return _clean_sql(_interaction(prompt))
    except Exception as exc:
        log.warning("Gemini SQL generation failed: %s", exc)
        if settings.ALLOW_DETERMINISTIC_FALLBACK:
            from .fallback_sql import build_fallback_sql
            return build_fallback_sql(question, schema_context)
        return ""


def summarize_with_llm(question: str, columns: List[str], rows: List[dict]) -> str:
    if not has_llm_runtime() or not get_settings().LLM_SUMMARIZER:
        return _grounded(question, columns, rows)
    prompt = f"""Answer only from these SQL results. Do not invent values.
Question: {question}
Columns: {columns}
Rows: {rows[:10]}
Total rows: {len(rows)}"""
    try:
        return _interaction(prompt) or _grounded(question, columns, rows)
    except Exception as exc:
        log.warning("Gemini summarize failed: %s", exc)
        return _grounded(question, columns, rows)


def _grounded(question: str, columns: List[str], rows: List[dict]) -> str:
    from .answer import grounded_answer
    return grounded_answer(question, columns, rows)


def repair_sql_with_llm(question: str, bad_sql: str, error: str, schema_context: str) -> str:
    if not has_llm_runtime():
        return ""
    prompt = f"""Return only a corrected single read-only SELECT statement.
Preserve every mandatory requirement in the verified plan and use only the
supplied schema.

Schema and verified plan:
{schema_context}
Question: {question}
Invalid SQL: {bad_sql}
Error: {error}
Corrected SQL:"""
    try:
        return _clean_sql(_interaction(prompt))
    except Exception as exc:
        log.warning("Gemini SQL repair failed: %s", exc)
        return ""
