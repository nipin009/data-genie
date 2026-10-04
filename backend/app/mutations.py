"""Admin-only human-approved data/schema mutations.

This module is intentionally separate from the read-only Text-to-SQL graph.
It creates a short-lived reviewed proposal first; execution is impossible until
an admin submits the proposal id with the exact confirmation value ``APPLY``.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import re
import uuid
from typing import Dict, Optional, Set

import sqlglot
import sqlglot.expressions as exp
from sqlalchemy import inspect, text

from .config import get_settings
from .db import get_engine
from .llm import has_llm_key, _gemini_model


@dataclass
class MutationProposal:
    proposal_id: str
    instruction: str
    sql: str
    summary: str
    risk: str
    expires_at: datetime
    status: str = "pending"


_pending: Dict[str, MutationProposal] = {}


def _allowed_tables() -> Set[str]:
    prefix = get_settings().TABLE_PREFIX
    return {name.lower() for name in inspect(get_engine()).get_table_names() if name.startswith(prefix)}


def validate_mutation(sql: str, known_tables: Optional[Set[str]] = None) -> str:
    """Validate one narrowly-scoped DML/DDL statement and return normalized SQL."""
    raw = (sql or "").strip().rstrip(";")
    if not raw or ";" in raw:
        raise ValueError("Exactly one mutation statement is required.")
    try:
        parsed = sqlglot.parse_one(raw, read="postgres")
    except Exception as exc:
        raise ValueError(f"SQL parse error: {exc}") from exc
    allowed = (exp.Insert, exp.Update, exp.Delete, exp.Create, exp.Drop, exp.Alter)
    if not isinstance(parsed, allowed):
        raise ValueError("Only INSERT, UPDATE, DELETE, CREATE TABLE, ALTER TABLE, or DROP TABLE is allowed here.")
    # Block nested commands and server-side escape hatches.
    if re.search(r"\b(grant|revoke|copy|vacuum|cluster|reindex|pg_sleep|dblink|lo_import)\b", raw, re.I):
        raise ValueError("Administrative commands and unsafe functions are not allowed.")
    tables = {table.name.lower() for table in parsed.find_all(exp.Table) if table.name}
    prefix = get_settings().TABLE_PREFIX.lower()
    if not tables or any(not table.startswith(prefix) for table in tables):
        raise ValueError(f"Mutations may target only {prefix}* business tables.")
    known = known_tables if known_tables is not None else _allowed_tables()
    # New dg_* table is allowed only as the target of CREATE; all other table
    # references must already exist in the reflected application schema.
    if not isinstance(parsed, exp.Create) and any(table not in known for table in tables):
        raise ValueError("Mutation references an unknown business table.")
    if isinstance(parsed, (exp.Update, exp.Delete)) and parsed.args.get("where") is None:
        raise ValueError("UPDATE and DELETE require a WHERE clause; bulk mutations are not allowed.")
    return parsed.sql(dialect="postgres")


def _generate_proposal(instruction: str) -> tuple[str, str, str]:
    if not has_llm_key():
        raise ValueError("Gemini is required to prepare a mutation proposal. Configure GOOGLE_API_KEY first.")
    schema = ", ".join(sorted(_allowed_tables()))
    prompt = f'''Create one cautious PostgreSQL mutation proposal for an administrator.
Allowed existing tables: {schema}
Return ONLY JSON with string fields sql, summary, risk.
Rules: one INSERT, UPDATE, DELETE, CREATE TABLE, ALTER TABLE, or DROP TABLE; target only dg_ tables; UPDATE/DELETE must contain a precise WHERE clause; never touch datagenie_ tables; do not use multiple statements; do not invent tables or columns. The proposal will require separate human approval before execution.
Administrator instruction: {instruction}'''
    raw = (_gemini_model().invoke(prompt).content or "").strip()
    if "```" in raw:
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    try:
        value = json.loads(raw)
        return str(value["sql"]), str(value.get("summary") or instruction), str(value.get("risk") or "Review the SQL before applying it.")
    except Exception as exc:
        raise ValueError("Gemini did not return a valid mutation proposal.") from exc


def preview_mutation(instruction: str) -> MutationProposal:
    sql, summary, risk = _generate_proposal(instruction)
    normalized = validate_mutation(sql)
    proposal = MutationProposal(
        proposal_id=f"mut-{uuid.uuid4().hex[:16]}", instruction=instruction, sql=normalized,
        summary=summary, risk=risk,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=get_settings().MUTATION_APPROVAL_TTL_SECONDS),
    )
    _pending[proposal.proposal_id] = proposal
    return proposal


def apply_mutation(proposal_id: str, confirmation: str) -> MutationProposal:
    proposal = _pending.get(proposal_id)
    if proposal is None:
        raise ValueError("Unknown or expired mutation proposal.")
    if proposal.status != "pending":
        raise ValueError(f"This proposal is already {proposal.status}.")
    if datetime.now(timezone.utc) >= proposal.expires_at:
        proposal.status = "expired"
        raise ValueError("This proposal expired. Create and review a new preview.")
    if confirmation != "APPLY":
        raise ValueError("Confirmation must exactly equal APPLY.")
    # Validate again immediately before executing to defend against any future
    # in-memory proposal corruption.
    proposal.sql = validate_mutation(proposal.sql)
    with get_engine().begin() as conn:
        result = conn.execute(text(proposal.sql))
        proposal.rows_affected = result.rowcount if result.rowcount is not None and result.rowcount >= 0 else None
    proposal.status = "applied"
    return proposal
