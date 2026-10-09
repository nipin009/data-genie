"""Safe live-value linking for natural-language filters.

Values are read only from reflected, non-sensitive text columns.  Matching a
user phrase such as "Books" to ``dg_categories.category_name`` turns an
otherwise implicit request into an explicit, verifiable SQL requirement.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Sequence, Tuple

from sqlalchemy import text

from .db import readonly_session
from .schema_catalog import metadata_for
from .schema_introspection import SchemaSnapshot
from .sql_validation import SENSITIVE_COLUMNS
from .query_spec import FilterSpec

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_DIRECT_IDENTIFIER_COLUMNS = {"first_name", "last_name", "employee_name", "customer_name", "phone", "email"}
_METRIC_WORDS = {"sales", "sale", "revenue", "orders", "order", "payments", "payment", "returns", "return", "inventory", "stock"}
_value_cache: Dict[Tuple[str, str, str, int], List[str]] = {}


def clear_entity_cache() -> None:
    """Clear safe value lookups after a seed, schema refresh, or mutation."""
    _value_cache.clear()


@dataclass
class EntityResolution:
    filters: List[FilterSpec] = field(default_factory=list)
    matched_values: List[str] = field(default_factory=list)

    def render(self) -> str:
        if not self.filters:
            return "LIVE VALUE RESOLUTION: no unambiguous business values were found."
        lines = ["LIVE VALUE RESOLUTION (these filters are mandatory):"]
        for item in self.filters:
            lines.append(f"- {item.table}.{item.column} = {item.value!r}")
        return "\n".join(lines)


def _is_text_column(type_name: str) -> bool:
    low = type_name.lower()
    return any(token in low for token in ("char", "text", "string", "varchar"))


def _candidate_columns(snapshot: SchemaSnapshot, selected: Sequence[str]) -> List[Tuple[str, str]]:
    candidates: List[Tuple[str, str]] = []
    for table_name in selected:
        table = snapshot.tables.get(table_name)
        if not table:
            continue
        catalog = metadata_for(table_name)
        enum_columns = set((catalog.enums if catalog else {}).keys())
        for column in table.columns:
            name = column.name.lower()
            if name in SENSITIVE_COLUMNS or name in _DIRECT_IDENTIFIER_COLUMNS or name.endswith("_id"):
                continue
            if _is_text_column(column.type) or column.name in enum_columns:
                candidates.append((table_name, column.name))
    return candidates


def bind_planned_filters(filters: Sequence[FilterSpec], snapshot: SchemaSnapshot, selected: Sequence[str]) -> None:
    """Bind an LLM-planned business field to the best safe live column.

    This is useful when a user supplies a value absent from the data ("Books"
    in a database without that category): the generated SQL should still query
    the right column and honestly return no rows, not silently drop the filter.
    """
    for item in filters:
        if item.table or item.column or item.source != "structured_plan":
            continue
        requested = set(_normalize(item.field).split())
        if not requested:
            continue
        ranked = []
        for table, column in _candidate_columns(snapshot, selected):
            table_terms = set(_normalize(table.removeprefix("dg_")).split())
            column_terms = set(_normalize(column).split())
            meta = metadata_for(table)
            description_terms = set()
            if meta:
                description_terms = set(_normalize(meta.columns.get(column, "")).split())
            score = 5 * len(requested & column_terms) + 3 * len(requested & table_terms) + len(requested & description_terms)
            if score:
                ranked.append((score, table, column))
        if ranked:
            _, table, column = sorted(ranked, reverse=True)[0]
            item.table, item.column = table, column
            item.field = f"{table}.{column}"
            item.source = "planned_field_binding"


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.lower()))


def resolve_entities(question: str, snapshot: SchemaSnapshot, selected: Sequence[str], max_values: int = 250) -> EntityResolution:
    """Find exact phrase matches in allowlisted business-value columns.

    Dynamic identifiers originate solely from SQLAlchemy reflection and are
    additionally checked before quoting. Values are never interpolated into a
    query; this lookup is read-only and the resolved value is passed as a bound
    parameter.
    """
    question_normalized = _normalize(question)
    if not question_normalized:
        return EntityResolution()
    matches: List[Tuple[int, int, str, str, str]] = []

    def collect(columns: Sequence[Tuple[str, str]]) -> None:
        with readonly_session() as conn:
            for table, column in columns:
                if not _IDENTIFIER.fullmatch(table) or not _IDENTIFIER.fullmatch(column):
                    continue
                key = (str(conn.engine.url), table, column, max_values)
                values = _value_cache.get(key)
                if values is None:
                    statement = text(
                        f'SELECT DISTINCT "{column}" AS value FROM "{table}" '
                        f'WHERE "{column}" IS NOT NULL LIMIT :limit'
                    )
                    values = [value for value in conn.execute(statement, {"limit": max_values}).scalars().all()
                              if isinstance(value, str)]
                    _value_cache[key] = values
                for raw in values:
                    if not isinstance(raw, str) or not raw.strip():
                        continue
                    normalized = _normalize(raw)
                    if normalized in _METRIC_WORDS:
                        continue
                    if len(normalized) >= 3 and re.search(rf"(?<![a-z0-9]){re.escape(normalized)}(?![a-z0-9])", question_normalized):
                        table_terms = set(_normalize(table.removeprefix("dg_")).split())
                        column_terms = set(_normalize(column).split())
                        relevance = sum(1 for term in table_terms | column_terms if term in question_normalized.split())
                        matches.append((len(normalized), relevance, table, column, raw))

    try:
        collect(_candidate_columns(snapshot, selected))
        # Lexical schema retrieval may not select the category table for a
        # phrase like "Books".  A bounded second pass over safe value columns
        # lets a real database value repair that miss; its table is then added
        # to the generation context by the graph.
        if not matches:
            remaining = [name for name in snapshot.tables if name not in selected]
            collect(_candidate_columns(snapshot, remaining))
    except Exception:
        return EntityResolution()

    # Prefer longer, more specific values and never bind the same value twice.
    resolution = EntityResolution()
    by_value = {}
    for match in matches:
        by_value.setdefault(match[4].lower(), []).append(match)
    for value_key, value_matches in by_value.items():
        ranked = sorted(value_matches, reverse=True)
        best = ranked[0]
        # A value shared by unrelated columns (for example "pending") must
        # not become two mandatory predicates.  Prefer the table/column named
        # in the request; otherwise leave a true tie to the SQL planner.
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1] and (ranked[0][2], ranked[0][3]) != (ranked[1][2], ranked[1][3]):
            continue
        _, _, table, column, value = best
        resolution.filters.append(FilterSpec(
            field=f"{table}.{column}", operator="equals", value=value,
            table=table, column=column, source="entity_resolution",
        ))
        resolution.matched_values.append(value)
    return resolution
