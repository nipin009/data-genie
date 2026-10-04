"""Gemini LLM wrapper with graceful offline fallback + LangSmith tracing hooks.

If GOOGLE_API_KEY is absent, all calls fall back to deterministic heuristics so
the app and tests run without network. When configured, uses langchain-google-genai.
"""
import os
from typing import List, Optional

from .config import get_settings
from .logging_config import log


def _tracing_enabled() -> bool:
    s = get_settings()
    return bool(s.LANGSMITH_TRACING and s.LANGSMITH_API_KEY)


def enable_langsmith() -> None:
    s = get_settings()
    if _tracing_enabled():
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = s.LANGSMITH_API_KEY
        os.environ["LANGCHAIN_PROJECT"] = s.LANGSMITH_PROJECT
        log.info("LangSmith tracing enabled for project %s", s.LANGSMITH_PROJECT)


def has_llm_key() -> bool:
    return bool(get_settings().GOOGLE_API_KEY)


def _gemini_model():
    from langchain_google_genai import ChatGoogleGenerativeAI
    s = get_settings()
    return ChatGoogleGenerativeAI(
        model=s.GEMINI_MODEL, google_api_key=s.GOOGLE_API_KEY,
        timeout=s.LLM_TIMEOUT_SECONDS, temperature=0.1, max_retries=1,
    )


def generate_sql_with_llm(question: str, schema_context: str, history: Optional[List[dict]] = None) -> str:
    """Return a single SELECT statement (no markdown). Falls back to template builder."""
    if not has_llm_key():
        if get_settings().ALLOW_DETERMINISTIC_FALLBACK:
            from .fallback_sql import build_fallback_sql
            return build_fallback_sql(question, schema_context)
        return ""
    try:
        enable_langsmith()
        llm = _gemini_model()
        settings = get_settings()
        dialect = "SQLite" if settings.DATABASE_URL.startswith("sqlite") else "PostgreSQL"
        prefix = settings.TABLE_PREFIX or ""
        like_rule = "Use LIKE for case-insensitive name matches." if dialect == "SQLite" else "Use ILIKE for case-insensitive name matches."
        hist = ""
        if history:
            hist = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in history[-6:])
        prompt = f"""You are a Text-to-SQL expert for {dialect}. Output ONLY one valid SELECT statement, no markdown, no explanation.

Rules:
- Use ONLY tables/columns from the schema context below. Never invent columns.
  All tables are prefixed {prefix!r}; always use their full physical names from the schema context.
- Single SELECT statement, must end with LIMIT (<=500).
- Prefer explicit JOINs following the JOINS AVAILABLE edges.
- {like_rule} Escape single quotes in SQL string literals.
- Date columns: order_date, payment_date, review_date, signup_date (YYYY-MM-DD).
- For relative periods such as “last year”, “last month”, and “last N days”, use the database's current-date functions rather than a hard-coded calendar year.
- Status values: dg_orders.status in ('pending','processing','shipped','delivered','cancelled','returned'); dg_payments.status in ('succeeded','failed','refunded','pending').
- Never generate INSERT/UPDATE/DELETE/DDL. Read-only SELECT only.

Schema:
{schema_context}

Conversation (for coreference):
{hist}

Question: {question}
SQL:"""
        resp = llm.invoke(prompt)
        sql = (resp.content or "").strip()
        # strip code fences if model adds them
        if "```" in sql:
            import re
            m = re.search(r"```(?:sql)?\s*(.*?)```", sql, re.S | re.I)
            if m:
                sql = m.group(1).strip()
        return sql
    except Exception as e:
        log.warning("Gemini SQL generation failed, using fallback: %s", e)
        if get_settings().ALLOW_DETERMINISTIC_FALLBACK:
            from .fallback_sql import build_fallback_sql
            return build_fallback_sql(question, schema_context)
        return ""


def summarize_with_llm(question: str, columns: List[str], rows: List[dict]) -> str:
    # A second remote model call is slower and cannot be proved numerically
    # grounded.  Deterministic rendering is the safe default; deployments may
    # explicitly enable prose summarization after accepting that trade-off.
    if not has_llm_key() or not get_settings().LLM_SUMMARIZER:
        from .answer import grounded_answer
        return grounded_answer(question, columns, rows)
    try:
        enable_langsmith()
        llm = _gemini_model()
        sample = rows[:10]
        prompt = f"""Answer the user question STRICTLY from the SQL results below. Do not invent numbers.
If results are empty, say no matching data was found. Mention the key figures only.

Question: {question}
Columns: {columns}
Rows (first {len(sample)}): {sample}
Total rows: {len(rows)}
Answer in 2-4 sentences, include exact numbers from results."""
        resp = llm.invoke(prompt)
        text = (resp.content or "").strip()
        # Guardrail: if LLM answer contains numbers not in results, fall back.
        return text or grounded_answer(question, columns, rows)
    except Exception as e:
        log.warning("Gemini summarize failed, using grounded fallback: %s", e)
        from .answer import grounded_answer
        return grounded_answer(question, columns, rows)


def repair_sql_with_llm(question: str, bad_sql: str, error: str, schema_context: str) -> str:
    if not has_llm_key():
        from .fallback_sql import repair_fallback_sql
        return repair_fallback_sql(bad_sql, error)
    try:
        enable_langsmith()
        llm = _gemini_model()
        dialect = "SQLite" if get_settings().DATABASE_URL.startswith("sqlite") else "PostgreSQL"
        prompt = f"""Fix this {dialect} SELECT so it executes. Output ONLY the fixed SELECT, no markdown.

Schema:
{schema_context}

Question: {question}
Bad SQL: {bad_sql}
Error: {error}
Fixed SQL:"""
        resp = llm.invoke(prompt)
        sql = (resp.content or "").strip()
        if "```" in sql:
            import re
            m = re.search(r"```(?:sql)?\s*(.*?)```", sql, re.S | re.I)
            if m:
                sql = m.group(1).strip()
        return sql
    except Exception as e:
        log.warning("Gemini repair failed: %s", e)
        from .fallback_sql import repair_fallback_sql
        return repair_fallback_sql(bad_sql, error)
