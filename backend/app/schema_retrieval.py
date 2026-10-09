"""Relevant-schema retrieval: pick minimal tables/columns for a question.

Strategy (no embeddings required, fast + deterministic):
1. Score tables by keyword overlap: table name, column names, metric synonyms.
2. Always expand via FK join graph (neighbors of top tables) so joins are possible.
3. Prune columns to those lexically relevant + PKs + FKs (needed for joins).
4. Render compact context for the LLM with row counts and join edges.
"""
import re
from typing import Dict, List, Set, Tuple

from .metrics import find_metrics
from .schema_introspection import SchemaSnapshot, TableInfo, find_join_path
from .schema_catalog import metadata_for
from .example_bank import examples_context

_TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(s: str) -> Set[str]:
    return set(_TOKEN.findall(s.lower()))


def score_tables(question: str, snapshot: SchemaSnapshot) -> List[Tuple[str, float]]:
    qtok = _tokens(question)
    metrics = find_metrics(question)
    metric_tables = {t for m in metrics for t in m.tables}
    try:
        from .tables import t as _t
        _ord, _items, _cust, _prod, _rev, _pay, _cats = (
            _t("orders"), _t("order_items"), _t("customers"), _t("products"),
            _t("product_reviews"), _t("payments"), _t("categories"),
        )
    except Exception:
        _ord, _items, _cust, _prod, _rev, _pay, _cats = (
            "dg_orders", "dg_order_items", "dg_customers", "dg_products",
            "dg_product_reviews", "dg_payments", "dg_categories",
        )
    scored: List[Tuple[str, float]] = []
    for tname, t in snapshot.tables.items():
        # Strip dg_ prefix for keyword matching so "orders" still matches "dg_orders".
        logical = tname[3:] if tname.startswith("dg_") else tname
        parts = _tokens(logical.replace("_", " ")) | _tokens(tname.replace("_", " "))
        overlap = len(qtok & parts) * 3.0
        col_overlap = 0.0
        for c in t.columns:
            ctok = _tokens(c.name.replace("_", " "))
            if qtok & ctok:
                col_overlap += 1.0
        bonus = 2.0 if tname in metric_tables else 0.0
        # generic domain boosts (physical dg_ names)
        generic = {"order": [_ord, _items], "revenue": [_ord, _items], "sales": [_ord, _items, _prod, _cats],
                   "customer": [_cust, _ord], "product": [_prod, _items],
                   "review": [_rev], "payment": [_pay], "categor": [_cats, _prod]}
        for key, tbls in generic.items():
            if key in question.lower() and tname in tbls:
                bonus += 1.5
        scored.append((tname, overlap + min(col_overlap, 8.0) + bonus))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored


def retrieve_relevant_schema(
    question: str, snapshot: SchemaSnapshot, top_k: int = 4, max_cols_per_table: int = 25
) -> Dict:
    scored = score_tables(question, snapshot)
    top = [t for t, s in scored if s > 0][:top_k] or [t for t, _ in scored[:2]]
    # Expand: include FK neighbors of top tables (1 hop) so joins resolve.
    neighbors: Set[str] = set(top)
    for t1, c1, t2, c2 in snapshot.join_edges:
        if t1 in top and t2 in snapshot.tables:
            neighbors.add(t2)
        if t2 in top and t1 in snapshot.tables:
            neighbors.add(t1)
    # Cap total tables at top_k+2
    ordered = top + [t for t, _ in scored if t in neighbors and t not in top]
    selected = ordered[: top_k + 2]

    qtok = _tokens(question)
    pruned: Dict[str, TableInfo] = {}
    for tname in selected:
        t = snapshot.tables[tname]
        keep: List = []
        for c in t.columns:
            ctok = _tokens(c.name.replace("_", " "))
            relevant = bool(qtok & ctok) or c.is_pk or c.is_fk
            # always keep common analytic columns
            if c.name in ("order_date", "total_amount", "quantity", "unit_price",
                          "rating", "amount", "status", "product_name", "category_id",
                          "customer_id", "order_id", "product_id", "payment_method",
                          "country", "city", "order_status", "created_at"):
                relevant = True
            if relevant:
                keep.append(c)
        if len(keep) < min(len(t.columns), 8):
            keep = t.columns[: max_cols_per_table]
        pruned[tname] = TableInfo(name=t.name, columns=keep[:max_cols_per_table],
                                  primary_keys=t.primary_keys, foreign_keys=t.foreign_keys,
                                  row_count=t.row_count)
    # Add explicit BFS paths between the strongest concepts. This makes a
    # 2–5 table bridge available even when an intermediate table had no direct
    # lexical match (e.g. region -> warehouse -> inventory -> product).
    if selected:
        anchor = selected[0]
        for target in list(selected[1:]):
            for edge in find_join_path(snapshot, anchor, target, max_depth=5):
                for table in (edge[0], edge[2]):
                    if table in snapshot.tables and table not in selected and len(selected) < top_k + 4:
                        selected.append(table)
                        pruned[table] = snapshot.tables[table]
    # Relevant join edges among selected
    edges = [(a, b, c, d) for (a, b, c, d) in snapshot.join_edges if a in selected and c in selected]
    return {"tables": pruned, "edges": edges, "scores": scored, "selected": selected}


def render_schema_context(retrieved: Dict, metrics_text: str = "") -> str:
    lines: List[str] = []
    for tname in retrieved["selected"]:
        t = retrieved["tables"][tname]
        meta = metadata_for(tname)
        heading = f"BUSINESS MEANING: {meta.description}\n" if meta else ""
        lines.append(heading + t.describe())
        if meta:
            descriptions = [f"{name}={desc}" for name, desc in meta.columns.items() if name in t.column_names]
            if descriptions:
                lines.append("  meanings: " + "; ".join(descriptions))
            for column, values in meta.enums.items():
                if column in t.column_names:
                    lines.append(f"  enum {column}: {', '.join(values)}")
    if retrieved["edges"]:
        lines.append("JOINS AVAILABLE:")
        for a, b, c, d in retrieved["edges"]:
            lines.append(f"  {a}.{b} = {c}.{d}")
    if metrics_text:
        lines.append(metrics_text)
    # The question is injected by the caller below only through selected
    # examples; this avoids carrying the entire example bank in every prompt.
    return "\n".join(lines)
