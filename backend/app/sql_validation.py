"""SQL parsing + validation with SQLGlot.

Enforces: single SELECT statement, read-only (no DDL/DML/DDL-ish or functions
like pg_sleep), known tables/columns only, LIMIT present, bounded.
Returns structured ValidationResult consumed by the LangGraph conditional edge.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

import sqlglot
import sqlglot.expressions as exp

FORBIDDEN_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "copy", "vacuum", "cluster", "reindex",
    "pg_sleep", "pg_terminate", "dblink", "lo_import",
}

# A database account must still be least-privileged, but this second boundary
# blocks user-defined and server-side functions such as pg_read_file.
ALLOWED_FUNCTIONS = {
    "SUM", "AVG", "COUNT", "MIN", "MAX", "COALESCE", "NULLIF", "LOWER", "UPPER",
    "CONCAT", "DATE_TRUNC", "TO_CHAR", "EXTRACT", "CAST", "ROUND", "ABS", "CEIL",
    "CEILING", "FLOOR", "SUBSTRING", "TRIM", "LENGTH", "CURRENT_DATE", "CURRENT_TIMESTAMP",
    "NOW", "DATE", "STRFTIME", "TIME_TO_STR", "CASE", "IF", "RANK", "DENSE_RANK", "ROW_NUMBER",
    "LAG", "LEAD", "DATE_PART", "TIMESTAMP_TRUNC",
}

# These fields are not needed for aggregate retail analytics and must never be
# returned by the chat API.  This is enforced at SQL-validation time as a
# defence in depth measure: the classifier can give a helpful explanation, but
# an LLM-generated query cannot bypass the policy.
SENSITIVE_COLUMNS = {
    "email", "phone", "date_of_birth", "address_line1", "address_line2",
    "postal_code", "ship_address", "ship_postal", "card_last4",
    "transaction_id", "serial_number",
}

ALLOWED_STATEMENT = "SELECT"


@dataclass
class ValidationResult:
    ok: bool
    error: Optional[str] = None
    tables: List[str] = field(default_factory=list)
    columns: List[str] = field(default_factory=list)
    has_limit: bool = False
    fixed_sql: Optional[str] = None  # auto-bounded version


def validate_sql(
    sql: str,
    known_tables: Optional[Dict[str, Set[str]]] = None,
    max_rows: int = 500,
    join_edges: Optional[List[Tuple[str, str, str, str]]] = None,
) -> ValidationResult:
    if not sql or not sql.strip():
        return ValidationResult(False, "Empty SQL.")
    s = sql.strip()
    if s.count(";") > 1 or (s.count(";") == 1 and not s.rstrip().endswith(";")):
        return ValidationResult(False, "Multiple statements are not allowed; provide a single SELECT.")
    s = s.rstrip().rstrip(";")

    try:
        parsed = sqlglot.parse_one(s, read="postgres")
    except Exception as e:
        return ValidationResult(False, f"SQL parse error: {e}")

    if not isinstance(parsed, exp.Select):
        # sqlglot may return Union etc.; allow Union of selects but nothing else
        if isinstance(parsed, exp.Union):
            pass
        else:
            return ValidationResult(False, f"Only SELECT queries allowed, got {type(parsed).__name__}.")

    if parsed.args.get("into") is not None:
        return ValidationResult(False, "SELECT INTO is not allowed.")

    # Must not contain DDL/DML sub-nodes (defensive)
    for node in parsed.walk(bfs=False):
        n = node[0] if isinstance(node, tuple) else node
        if isinstance(n, (exp.Insert, exp.Update, exp.Delete, exp.Drop, exp.Create,
                          exp.TruncateTable if hasattr(exp, "TruncateTable") else exp.Command,
                          exp.Command, exp.Copy if hasattr(exp, "Copy") else exp.Semicolon)):
            return ValidationResult(False, f"Non-SELECT node not allowed: {type(n).__name__}.")

    # SQLGlot represents standard functions with specialised expression types
    # and extension/UDF calls as Anonymous.  Permit only an intentionally small
    # analytics function set.
    for fn in parsed.find_all(exp.Func):
        try:
            name = (fn.sql_name() or "").upper()
        except Exception:
            name = ""
        if isinstance(fn, exp.Anonymous):
            name = (fn.name or "").upper()
        # SQLGlot represents boolean operators such as AND as Func subclasses
        # in some dialect/version combinations.  They are operators, not
        # callable database functions, and rejecting them breaks every query
        # with a compound predicate.
        if isinstance(fn, (exp.And, exp.Or, exp.Not)):
            continue
        if name and name not in ALLOWED_FUNCTIONS:
            return ValidationResult(False, f"Function '{name}' is not allowed.")

    tables = [t.name.lower() for t in parsed.find_all(exp.Table)]
    if known_tables is not None:
        known_lower = {k.lower(): {c.lower() for c in v} for k, v in known_tables.items()}
        cte_names = {
            (cte.alias_or_name or "").lower()
            for cte in parsed.find_all(exp.CTE)
            if (cte.alias_or_name or "")
        }
        for t in parsed.find_all(exp.Table):
            if t.name.lower() not in known_lower and t.name.lower() not in cte_names:
                return ValidationResult(False, f"Unknown table '{t.name}'. Use only schema tables.")
        # SELECT aliases (e.g. AS revenue) are legal in GROUP BY / ORDER BY.
        aliases = set()
        for a in parsed.find_all(exp.Alias):
            try:
                aliases.add((a.alias_or_name or "").lower())
            except Exception:
                pass
        # A wildcard projection can include restricted PII columns without
        # naming them, so column-by-column checks alone are insufficient.
        # COUNT(*) remains valid because its star is nested in an aggregate,
        # not used as a SELECT-list projection.
        for select in parsed.find_all(exp.Select):
            for projection in select.expressions:
                target = projection.this if isinstance(projection, exp.Alias) else projection
                if isinstance(target, exp.Star) or (isinstance(target, exp.Column) and target.name == "*"):
                    return ValidationResult(False, "Wildcard projections are not allowed; select approved columns explicitly.")

        for col in parsed.find_all(exp.Column):
            tbl = (col.table or "").lower()
            cname = (col.name or "").lower()
            if cname == "*" or cname == "":
                continue
            if cname in SENSITIVE_COLUMNS:
                return ValidationResult(False, f"Column '{col.name}' is restricted to protect personal or payment data.")
            if cname in aliases:
                continue
            if tbl:
                # resolve alias -> real table via FROM/JOIN aliases
                alias_map = {}
                for t in parsed.find_all(exp.Table):
                    alias_map[(t.alias_or_name or "").lower()] = t.name.lower()
                    alias_map[t.name.lower()] = t.name.lower()
                real = alias_map.get(tbl, tbl)
                if real in known_lower and cname not in known_lower[real]:
                    return ValidationResult(False, f"Unknown column '{col.sql()}'.")
            else:
                # bare column: must exist in at least one referenced table (else typo/hallucination)
                ref_tables = [t.name.lower() for t in parsed.find_all(exp.Table)]
                known_refs = [rt for rt in ref_tables if rt in known_lower]
                if known_refs and all(cname not in known_lower.get(rt, set()) for rt in known_refs):
                    return ValidationResult(False, f"Unknown column '{col.sql()}'.")

    # Reject fabricated joins when both sides are physical tables and the ON
    # predicate names a column pair not represented by the reflected FK graph.
    # Complex predicates/CTEs are deliberately left to the normal column and
    # execution checks, because a strict syntactic rule would reject valid SQL.
    if join_edges:
        alias_map = {}
        for table in parsed.find_all(exp.Table):
            alias_map[(table.alias_or_name or "").lower()] = table.name.lower()
            alias_map[table.name.lower()] = table.name.lower()
        allowed_pairs = {
            frozenset(((a.lower(), b.lower()), (c.lower(), d.lower())))
            for a, b, c, d in join_edges
        }
        for join in parsed.find_all(exp.Join):
            on = join.args.get("on")
            if on is None:
                continue
            pairs = []
            for eq in on.find_all(exp.EQ):
                left, right = eq.left, eq.right
                if isinstance(left, exp.Column) and isinstance(right, exp.Column) and left.table and right.table:
                    pairs.append(((alias_map.get(left.table.lower(), left.table.lower()), left.name.lower()),
                                  (alias_map.get(right.table.lower(), right.table.lower()), right.name.lower())))
            if pairs and not any(frozenset(pair) in allowed_pairs for pair in pairs):
                return ValidationResult(False, "JOIN condition does not match an allowed foreign-key relationship.")

    has_limit = parsed.args.get("limit") is not None
    fixed = s
    if not has_limit:
        fixed = s + f" LIMIT {max_rows}"
    else:
        # clamp excessive limits
        try:
            lim = parsed.args["limit"].expression
            n = int(lim.sql())
            if n > max_rows:
                fixed = re.sub(r"(?i)\blimit\s+\d+", f"LIMIT {max_rows}", s)
        except Exception:
            pass
    cols = [c.sql() for c in parsed.find_all(exp.Column)][:50]
    return ValidationResult(True, None, sorted(set(tables)), cols, True, fixed)
