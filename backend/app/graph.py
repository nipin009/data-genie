"""LangGraph workflow: explicit routing with conditional validation, clarification, bounded repair.

Nodes: classify -> (clarify | unsupported/unrelated | retrieve) -> generate -> validate
  -> (execute | repair x<=MAX_REPAIR_RETRIES -> validate) -> answer+visualize

State preserves conversation. Never executes SQL until classification is in_scope
and validation passes.
"""
from typing import Any, Dict, List, Optional, TypedDict

from langgraph.graph import END, StateGraph

from .answer import grounded_answer
from .classifier import classify
from .config import get_settings
from .db import execute_readonly_sql, get_engine, query_cost
from .llm import generate_sql_with_llm, repair_sql_with_llm, summarize_with_llm
from .logging_config import log
from .metrics import find_metrics, metrics_context
from .query_spec import QuerySpec, build_query_spec
from .schema_introspection import SchemaSnapshot, extract_schema
from .schema_retrieval import render_schema_context, retrieve_relevant_schema
from .example_bank import examples_context
from .semantic_validation import validate_semantics
from .sql_validation import validate_sql
from .visualization import choose_chart


class AgentState(TypedDict, total=False):
    question: str
    history: List[Dict[str, str]]
    classification: str
    class_reason: str
    missing: List[str]
    clarification_questions: List[str]
    query_spec: Dict[str, Any]
    schema_context: str
    selected_tables: List[str]
    sql: str
    validation_error: Optional[str]
    retry_count: int
    columns: List[str]
    rows: List[Dict[str, Any]]
    row_count: int
    truncated: bool
    chart: Dict[str, Any]
    answer: str
    done: bool
    unhandled_fallback: bool


_schema_cache: Optional[SchemaSnapshot] = None


def get_schema_snapshot(engine=None) -> SchemaSnapshot:
    global _schema_cache
    if _schema_cache is None:
        try:
            prefix = get_settings().TABLE_PREFIX or ""
        except Exception:
            prefix = "dg_"
        snap = extract_schema(engine or get_engine(), table_prefix=prefix)
        # Scope the app to its own dg_-prefixed tables: local_db is shared with
        # other projects (e.g. daily_hustle_*), which must never be queried.
        if prefix:
            snap.tables = {n: ti for n, ti in snap.tables.items() if n.startswith(prefix)}
            snap.join_edges = [e for e in snap.join_edges if e[0] in snap.tables and e[2] in snap.tables]
        _schema_cache = snap
    return _schema_cache


def reset_schema_cache() -> None:
    global _schema_cache
    _schema_cache = None


# ---- nodes ----
def node_classify(state: AgentState) -> AgentState:
    snap = get_schema_snapshot()
    c = classify(state["question"], snap.table_names(), state.get("history"))
    log.info("classify '%s' -> %s (%s)", state["question"][:80], c.label, c.reason)
    return {"classification": c.label, "class_reason": c.reason, "missing": c.missing,
            "clarification_questions": c.questions}


def node_retrieve(state: AgentState) -> AgentState:
    snap = get_schema_snapshot()
    metrics = find_metrics(state["question"])
    retrieved = retrieve_relevant_schema(state["question"], snap)
    spec = build_query_spec(state["question"])
    ctx = (render_schema_context(retrieved, metrics_context(metrics)) + "\n" +
           examples_context(state["question"]) + "\n" + spec.render())
    return {"schema_context": ctx, "selected_tables": retrieved["selected"], "query_spec": spec.as_dict()}


def node_schema_answer(state: AgentState) -> AgentState:
    """Serve relevant live schema metadata without generating or executing SQL."""
    snap = get_schema_snapshot()
    retrieved = retrieve_relevant_schema(state["question"], snap, top_k=6)
    q = state["question"].lower()
    names = sorted(snap.table_names())
    prefix = get_settings().TABLE_PREFIX or ""

    # Follow the requested information depth.  Schema enumeration is common
    # in chat, and returning every column for "names only" overwhelms the
    # answer and makes the follow-up appear ignored.
    wants_names_only = "only" in q and ("table" in q or "names" in q)
    wants_count = "how many table" in q or "number of table" in q
    wants_relationships = any(word in q for word in ("relationship", "foreign key", "join graph", "connect"))
    wants_columns = "column" in q or "field" in q
    wants_full_schema = "schema" in q and any(word in q for word in ("each", "every", "all", "full"))

    if wants_names_only:
        answer = "\n".join(names)
        selected = names
    elif wants_count:
        answer = f"There are {len(names)} tables in the connected database."
        selected = names
    elif wants_relationships:
        relevant = [edge for edge in snap.join_edges
                    if any(token in q for token in (edge[0].lower(), edge[2].lower(),
                                                      edge[0].removeprefix(prefix).lower(), edge[2].removeprefix(prefix).lower()))]
        edges = relevant or snap.join_edges
        answer = ("TABLE RELATIONSHIPS:\n" + "\n".join(f"- {a}.{b} → {c}.{d}" for a, b, c, d in edges)
                  if edges else "I found no foreign-key relationships.")
        selected = sorted({table for edge in edges for table in (edge[0], edge[2])})
    elif wants_columns:
        target = next((name for name in names if name.lower() in q), None)
        if not target:
            target = next((name for name in names if name.removeprefix(prefix).lower() in q), None)
        if target:
            answer = f"Columns in {target}: " + ", ".join(c.name for c in snap.tables[target].columns)
            selected = [target]
        else:
            answer = "Which table would you like columns for? Available tables: " + ", ".join(names)
            selected = names
    elif wants_full_schema:
        sections = [f"{name}: " + ", ".join(c.name for c in snap.tables[name].columns) for name in names]
        answer = "Schema for each available table:\n" + "\n".join(sections)
        selected = names
    elif "which table" in q or "which tables" in q:
        answer = ("Relevant tables: " + ", ".join(retrieved["selected"]) + "\n\n" +
                  render_schema_context(retrieved))
        selected = retrieved["selected"]
    else:
        answer = "Available tables: " + ", ".join(names)
        selected = names
    return {"answer": answer, "done": True, "columns": [], "rows": [], "row_count": 0,
            "selected_tables": selected, "chart": {"type": "none", "reason": "schema metadata request"}}


def node_assistant_info(state: AgentState) -> AgentState:
    """Answer product/help questions without treating them as database queries."""
    q = state["question"].lower()
    if any(x in q for x in ("hello", " hi", "hey", "morning", "afternoon", "evening")):
        answer = ("Hi! I’m Data Genie. I can answer questions about your store data—orders, customers, "
                  "products, payments, categories, and reviews. What would you like to explore?")
    elif any(x in q for x in ("how do you work", "how does this work", "how does this app work", "how to use", "how do i use")):
        answer = ("Ask a plain-language question about the store data, such as ‘Revenue by category last month’ "
                  "or ‘Top 5 customers by lifetime spend.’ I clarify ambiguous requests, generate a read-only "
                  "query, validate it against the schema, and show grounded results.")
    elif any(x in q for x in ("security", "privacy", "safe", "personal data")):
        answer = ("Data Genie runs read-only SELECT queries and restricts direct personal and payment identifiers. "
                  "It can provide aggregated analytics, but not customer emails, phone numbers, addresses, card data, "
                  "or transaction IDs.")
    else:
        answer = ("I’m Data Genie, a store-data assistant. I can analyze revenue, orders, customers, products, "
                  "payments, returns, and reviews; explain the available schema; and create charts. Ask ‘What can you do?’ "
                  "or try ‘Show monthly revenue by category.’")
    return {"answer": answer, "done": True, "columns": [], "rows": [], "row_count": 0,
            "chart": {"type": "none", "reason": "Data Genie information request"}}


def node_generate(state: AgentState) -> AgentState:
    sql = generate_sql_with_llm(state["question"], state.get("schema_context", ""), state.get("history"))
    log.info("generated SQL: %s", sql[:200])
    return {"sql": sql, "retry_count": state.get("retry_count", 0), "unhandled_fallback": not bool(sql.strip())}


def node_unhandled_fallback(state: AgentState) -> AgentState:
    return {
        "answer": (
            "That is a valid store-data question, but this deployment's offline query templates "
            "do not support that exact calculation yet, so I won't substitute a different query. "
            "Try a supported metric such as revenue, order count, average order value, ratings, "
            "returns, payments, or a category/country/segment/brand breakdown."
        ),
        "done": True,
        "sql": None,
        "columns": [],
        "rows": [],
        "row_count": 0,
        "chart": {"type": "none", "reason": "offline query capability not available"},
    }


def node_validate(state: AgentState) -> AgentState:
    settings = get_settings()
    snap = get_schema_snapshot()
    known = {t: set(info.column_names) for t, info in snap.tables.items()}
    res = validate_sql(state.get("sql", ""), known, settings.MAX_ROWS, join_edges=snap.join_edges)
    if res.ok:
        sql = res.fixed_sql or state["sql"]
        raw_spec = state.get("query_spec")
        spec = QuerySpec(**raw_spec) if raw_spec else None
        # Filters are serialized dictionaries by LangGraph; reconstruct them lazily.
        if spec and raw_spec:
            from .query_spec import FilterSpec
            spec.filters = [x if isinstance(x, FilterSpec) else FilterSpec(**x) for x in raw_spec.get("filters", [])]
        semantic_error = validate_semantics(sql, spec)
        if semantic_error:
            return {"validation_error": f"Semantic validation failed: {semantic_error}"}
        return {"validation_error": None, "sql": sql}
    return {"validation_error": res.error}


def node_execute(state: AgentState) -> AgentState:
    try:
        max_cost = get_settings().MAX_QUERY_COST
        if max_cost > 0:
            cost = query_cost(state["sql"])
            if cost is not None and cost > max_cost:
                return {"validation_error": f"Query planner cost {cost:.0f} exceeds configured limit {max_cost:.0f}", "done": False}
        out = execute_readonly_sql(state["sql"])
        chart = choose_chart(out["columns"], out["rows"], state["question"])
        answer = summarize_with_llm(state["question"], out["columns"], out["rows"])
        # Safety: ensure grounded fallback if LLM path invented content — grounded_answer is default offline.
        if not out["rows"]:
            answer = grounded_answer(state["question"], out["columns"], out["rows"], chart)
        return {"columns": out["columns"], "rows": out["rows"], "row_count": out["row_count"],
                "truncated": out["truncated"], "chart": chart, "answer": answer, "done": True}
    except Exception as e:
        log.warning("execution failed: %s", e)
        return {"validation_error": f"Execution error: {e}", "done": False}


def node_repair(state: AgentState) -> AgentState:
    settings = get_settings()
    rc = state.get("retry_count", 0) + 1
    fixed = repair_sql_with_llm(state["question"], state.get("sql", ""),
                                state.get("validation_error", ""), state.get("schema_context", ""))
    log.info("repair attempt %d: %s", rc, fixed[:200])
    return {"sql": fixed, "retry_count": rc}


def node_clarify(state: AgentState) -> AgentState:
    qs = state.get("clarification_questions") or ["Could you clarify what you'd like to know?"]
    answer = ("I need a bit more detail before I query the database:\n" +
              "\n".join(f"{i+1}. {q}" for i, q in enumerate(qs)))
    return {"answer": answer, "done": True, "columns": [], "rows": [],
            "chart": {"type": "none", "reason": "clarification needed"}}


def node_offtrack(state: AgentState) -> AgentState:
    label = state.get("classification")
    reason = state.get("class_reason", "")
    if label == "unrelated":
        answer = ("That's outside what I can help with — I answer questions about the store "
                  "database (orders, customers, products, payments, reviews). "
                  "Try asking e.g. 'What was total revenue last quarter by category?'")
    elif label == "not_in_schema":
        answer = ("That question is data-related, but the connected store database does not contain "
                  "the required fields. I can answer questions about orders, customers, products, "
                  "payments, categories, and reviews. If you connect the missing dataset, I can query it too.")
    else:
        answer = (f"I can't run that as a read-only SQL query. {reason} "
                  "I support SELECT-only questions about orders, customers, products, "
                  "payments, and reviews (aggregations, trends, comparisons, top-N).")
    return {"answer": answer, "done": True, "columns": [], "rows": [],
            "chart": {"type": "none", "reason": label or "offtrack"}}


# ---- routing ----
def route_after_classify(state: AgentState) -> str:
    label = state.get("classification")
    if label == "in_scope":
        return "retrieve"
    if label == "schema_request":
        return "schema"
    if label == "assistant_info":
        return "assistant_info"
    if label == "ambiguous":
        return "clarify"
    return "offtrack"


def route_after_validate(state: AgentState) -> str:
    if not state.get("validation_error"):
        return "execute"
    if state.get("retry_count", 0) >= get_settings().MAX_REPAIR_RETRIES:
        return "giveup"
    return "repair"


def route_after_generate(state: AgentState) -> str:
    return "unhandled" if state.get("unhandled_fallback") else "validate"


def node_giveup(state: AgentState) -> AgentState:
    err = state.get("validation_error", "validation failed")
    return {"answer": (f"I couldn't build a safe query for that ({err}). "
                       "Try rephrasing with a specific metric, date range, or grouping."),
            "done": True, "columns": [], "rows": [], "chart": {"type": "none", "reason": "validation failed"}}


def build_graph():
    g = StateGraph(AgentState)
    g.add_node("classify", node_classify)
    g.add_node("retrieve", node_retrieve)
    g.add_node("schema", node_schema_answer)
    g.add_node("assistant_info", node_assistant_info)
    g.add_node("generate", node_generate)
    g.add_node("unhandled", node_unhandled_fallback)
    g.add_node("validate", node_validate)
    g.add_node("execute", node_execute)
    g.add_node("repair", node_repair)
    g.add_node("clarify", node_clarify)
    g.add_node("offtrack", node_offtrack)
    g.add_node("giveup", node_giveup)
    g.set_entry_point("classify")
    g.add_conditional_edges("classify", route_after_classify,
                            {"retrieve": "retrieve", "schema": "schema", "assistant_info": "assistant_info", "clarify": "clarify", "offtrack": "offtrack"})
    g.add_edge("retrieve", "generate")
    g.add_edge("schema", END)
    g.add_edge("assistant_info", END)
    g.add_conditional_edges("generate", route_after_generate,
                            {"validate": "validate", "unhandled": "unhandled"})
    g.add_conditional_edges("validate", route_after_validate,
                            {"execute": "execute", "repair": "repair", "giveup": "giveup"})
    g.add_edge("repair", "validate")
    # Execution failures carry validation_error and receive the same bounded repair path.
    g.add_conditional_edges("execute", route_after_validate,
                            {"execute": END, "repair": "repair", "giveup": "giveup"})
    g.add_edge("clarify", END)
    g.add_edge("offtrack", END)
    g.add_edge("giveup", END)
    g.add_edge("unhandled", END)
    # After execute, a validation/execution error routes back? execute sets validation_error;
    # check here: if execute failed, allow bounded retry via repair.
    return g.compile()


_GRAPH = None


def get_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_graph()
    return _GRAPH


def run_question(question: str, history: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    graph = get_graph()
    out = graph.invoke({"question": question, "history": history or [], "retry_count": 0})
    return {
        "classification": out.get("classification"),
        "class_reason": out.get("class_reason"),
        "query_spec": out.get("query_spec", {}),
        "clarification_questions": out.get("clarification_questions", []),
        "selected_tables": out.get("selected_tables", []),
        "sql": out.get("sql"),
        "validation_error": out.get("validation_error"),
        "columns": out.get("columns", []),
        "rows": out.get("rows", []),
        "row_count": out.get("row_count", 0),
        "truncated": out.get("truncated", False),
        "chart": out.get("chart", {"type": "table"}),
        "answer": out.get("answer", ""),
    }
