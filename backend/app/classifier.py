"""Request classification: in_scope | assistant_info | ambiguous | unsupported | unrelated.

Runs BEFORE any SQL generation. Heuristic-first (fast, offline-safe), with an
LLM hook for refinement when a key is configured. Never guesses: when essential
slots (metric, date range, grouping, filter entity) are missing or vague, the
request is 'ambiguous' and the graph routes to clarification.

- in_scope: clear data question answerable from schema.
- ambiguous: data question but missing/vague essential detail.
- unsupported: data-adjacent but not executable (writes, DDL, row-level PII dump
  beyond limits, forecasting without data, etc.).
- unrelated: not about the database at all (greetings handled as unrelated-smalltalk).
"""
import re
import json
from dataclasses import dataclass, field
from typing import List, Optional

VAGUE_PATTERNS = [
    r"\b(recent|recently|lately|top|best|popular|high|low)\b(?!\s*(10|5|3|\d+))",
    r"\b(my|our)\b",
    r"\b(some|several|a few|many|various)\b",
    r"\b(thing|stuff|data|info|details)\b\s*$",
]

WRITE_PATTERNS = [
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke)\b",
    r"\bchange\s+the\s+(price|data|record)",
    r"\badd\s+a\s+(new\s+)?(product|customer|order|row)",
]

UNRELATED_HINTS = [
    "joke", "poem", "story", "weather", "python", "javascript", "capital of", "president",
    "movie", "song", "recipe", "sports",
]

# These are legitimate interactions with the product, although they do not
# need SQL. Keep them distinct from unrelated small talk so the application is
# welcoming and can explain its own scope and operation.
ASSISTANT_INFO_PATTERNS = [
    "data genie", "this app", "this tool", "what can you do", "how do you work",
    "how does this work", "how to use", "how do i use", "help", "who are you",
    "your capability", "your capabilities", "what do you support",
]
GREETING_PATTERNS = ("hello", "hi", "hey", "good morning", "good afternoon", "good evening", "thanks", "thank you", "bye")

FORECAST_PATTERNS = [r"\bpredict\b", r"\bforecast\b", r"\bwill\s+.*\s+happen", r"\bnext\s+year\b.*\b(predict|forecast)"]

# The chat surface is an analytics tool, not a customer/contact lookup tool.
# Keep this wording-oriented so aggregate questions such as "orders by country"
# remain valid while requests for identifying/payment details get a clear answer.
SENSITIVE_DATA_PATTERNS = [
    r"\b(?:list|show|give|find|export|get|display)\b.*\b(?:customer )?emails?\b",
    r"\b(?:list|show|give|find|export|get|display)\b.*\b(?:phone numbers?|telephone|addresses?|date of birth|dob)\b",
    r"\b(?:list|show|give|find|export|get|display)\b.*\b(?:card last ?4|card number|transaction ids?)\b",
    r"\b(?:what is|what's)\b.*\b(?:email|phone number|address|date of birth)\b",
]

# Data-looking requests for business concepts this schema does not model.  Keep
# this deliberately narrow: the authoritative schema now includes inventory,
# employees, suppliers, campaigns, subscriptions, and conversion membership.
# A stale deny-list is worse than no deny-list because it silently rejects
# answerable questions before retrieval has a chance to inspect the schema.
MISSING_SCHEMA_HINTS = [
    "warehouse temperature", "payroll", "ad spend", "web traffic",
]

SCHEMA_REQUEST_PATTERNS = [
    r"\bhow many tables?\b",
    r"\b(?:list|show|give|what are)\s+(?:all\s+)?(?:the\s+)?tables?\b",
    r"\b(?:name|list|show|give)\s+(?:all|al)\s+(?:the\s+)?tables?\b",
    r"\b(?:list|show|give|what are)\s+(?:the\s+)?table\s+(?:names?|anmes|nmaes)\b",
    r"\btable\s+(?:names?|anmes|nmaes)\s+(?:only|please)?\b",
    r"\b(?:describe|show|list|give)\s+(?:the\s+)?(?:database )?schema\b",
    r"\b(?:give|show|list|describe)\b.*\bschema\s+(?:of|for)\s+(?:each|every|all)\s+tables?\b",
    r"\b(?:each|every|all)\s+tables?\b.*\bschema\b",
    r"\b(?:columns?|fields?)\s+(?:in|of|for)\b",
    r"\b(?:name|list|show|give|what are)\b.*\b(?:columns?|fields?)\b.*\b(?:in|of|for)\b",
    r"\bwhich\s+tables?\b.*\b(?:money|financial|revenue|payment|invoice|cost|price|amount)\b",
    r"\b(?:table )?(?:relationships?|foreign keys?|join graph)\b",
    r"\bwhich table\s+(?:has|contains)\b",
]

AMBIGUITY_QUESTIONS = {
    "date_range": "Which date range should I use? (e.g. last 30 days, 2024-Q1, 2025-01-01 to 2025-03-31)",
    "metric": "Which metric do you mean exactly? (e.g. revenue = sum of line totals, order count, average order value)",
    "grouping": "How should I group the results? (e.g. by month, by product category, by country)",
    "entity": "Which specific {kind} do you mean? Please give a name or ID.",
    "top_n": "How many rows should I return (Top N)?",
}


@dataclass
class Classification:
    label: str  # in_scope | assistant_info | schema_request | ambiguous | unsupported | not_in_schema | unrelated
    reason: str
    missing: List[str] = field(default_factory=list)
    questions: List[str] = field(default_factory=list)
    confidence: float = 0.8


def _has(tokens: List[str], text: str) -> bool:
    return any(t in text for t in tokens)


VALID_LABELS = {"in_scope", "assistant_info", "schema_request", "ambiguous", "unsupported", "not_in_schema", "unrelated"}


def _classify_with_llm(question: str, table_names: Optional[List[str]], history: Optional[List[dict]] = None) -> Optional[Classification]:
    """Use Gemini structured JSON classification before schema retrieval.

    Only table names are supplied at this stage, never the complete schema.
    A conservative local fallback is retained for offline development and model
    outages; production classification does not use regex routing.
    """
    try:
        from .llm import has_llm_key, _gemini_model, enable_langsmith
        if not has_llm_key():
            return None
        enable_langsmith()
        names = ", ".join(table_names or [])
        recent = "\n".join(f"{m.get('role')}: {m.get('content')}" for m in (history or [])[-6:])
        prompt = f'''Classify this request for a read-only business analytics assistant.
Available table names: {names}
Return ONLY JSON with keys label, reason, missing, questions. label must be one of:
in_scope, assistant_info, schema_request, ambiguous, unsupported, not_in_schema, unrelated.
Use schema_request for table/column/relationship questions. Requests such as “name/list/show/give all tables in my DB”, including obvious spelling mistakes such as “al”, are ALWAYS schema_request, never in_scope. Use ambiguous only when a required detail cannot be inferred from the semantic catalog or schema: “recent” requires a date range, “top” requires N, and vague performance/comparison requests need a metric or grouping. A named metric with a catalog definition (for example total revenue) is clear, and no stated date range means all available data; do NOT ask for a revenue-definition or date-range clarification in that case. Superlatives such as weakest, highest, or broadest are clear ranking requests when their metric and entity are named; they do not need a Top-N clarification. Use unsupported for writes, destructive SQL, forecasts, or direct contact/payment identifiers. Use unrelated only when it has no connection to available business data. Treat users as customers. Do not generate SQL.
Recent conversation (resolve pronouns and follow-ups from it):
{recent}
Question: {question}'''
        raw = (_gemini_model().invoke(prompt).content or "").strip()
        if "```" in raw:
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
        data = json.loads(raw)
        label = data.get("label")
        if label not in VALID_LABELS:
            return None
        missing = data.get("missing") if isinstance(data.get("missing"), list) else []
        questions = data.get("questions") if isinstance(data.get("questions"), list) else []
        return Classification(label, str(data.get("reason") or "LLM intent classification."), missing[:3], questions[:3], 0.9)
    except Exception:
        return None


def classify(question: str, table_names: Optional[List[str]] = None, history: Optional[List[dict]] = None) -> Classification:
    llm_result = _classify_with_llm(question, table_names, history)
    if llm_result is not None:
        return llm_result
    from .config import get_settings
    if get_settings().ALLOW_DETERMINISTIC_FALLBACK:
        return _classify_fallback(question, table_names)
    # Generic Text-to-SQL cannot be honestly emulated with phrase-specific
    # routing. Require the configured LLM rather than silently applying rules.
    return Classification("unsupported", "Generic Text-to-SQL requires a configured Gemini API key; no query was generated.")


def _classify_fallback(question: str, table_names: Optional[List[str]] = None) -> Classification:
    q = (question or "").strip()
    ql = q.lower()
    if not q:
        return Classification("ambiguous", "Empty question.", ["intent"],
                              ["What would you like to know about the store data?"], 0.9)
    if len(q.split()) <= 4 and any(re.fullmatch(rf"[\W\s]*{re.escape(h)}[!,.\W\s]*", ql) for h in GREETING_PATTERNS):
        return Classification("assistant_info", "Greeting or conversational interaction.", [], [], 0.98)

    for pat in WRITE_PATTERNS:
        if re.search(pat, ql):
            return Classification("unsupported", "Write/DDL operations are not supported; this app is read-only.",
                                  [], [], 0.95)
    for pat in FORECAST_PATTERNS:
        if re.search(pat, ql):
            return Classification("unsupported", "Forecasting/prediction is not supported without a model and history.",
                                  [], [], 0.85)

    for pat in SENSITIVE_DATA_PATTERNS:
        if re.search(pat, ql):
            return Classification(
                "unsupported",
                "Direct personal and payment identifiers are restricted. I can provide aggregated, de-identified analytics instead.",
                [], [], 0.98,
            )

    if any(h in ql for h in MISSING_SCHEMA_HINTS):
        return Classification("not_in_schema", "That business concept is not represented in the connected database.", [], [], 0.9)

    # Metadata questions use the live schema snapshot and must never fall
    # through into the generic data-query fallback.
    if any(re.search(pat, ql) for pat in SCHEMA_REQUEST_PATTERNS):
        return Classification("schema_request", "Request is for database schema metadata.", [], [], 0.98)

    if any(h in ql for h in ASSISTANT_INFO_PATTERNS):
        return Classification("assistant_info", "Question is about Data Genie or how to use it.", [], [], 0.95)

    data_words = ["order", "revenue", "sale", "customer", "user", "product", "categor",
                  "payment", "review", "rating", "refund", "return", "discount",
                  "inventory", "stock", "warehouse", "shipment", "supplier", "employee",
                  "department", "region", "invoice", "campaign", "conversion", "ticket",
                  "support", "plan", "subscription", "vendor", "total", "average", "count",
                  "sum", "top", "list", "show", "how many", "how much", "trend",
                  "compare", "breakdown", "table", "chart", "orders", "customers", "products"]
    looks_like_data = _has(data_words, ql) or (table_names and any(t in ql for t in table_names))

    unrelated_hit = _has(UNRELATED_HINTS, ql)
    if unrelated_hit and not looks_like_data:
        return Classification("unrelated", "Question is not about the available store database.", [], [], 0.9)

    if not looks_like_data:
        # Could still be ambiguous data question ("show me recent stuff")
        if _has(["show", "list", "get", "find", "give", "recent", "data"], ql):
            return Classification(
                "ambiguous", "Intent is vague; need metric/entity/date clarification.",
                ["metric", "date_range"],
                [AMBIGUITY_QUESTIONS["metric"], AMBIGUITY_QUESTIONS["date_range"]], 0.7)
        return Classification("unrelated", "No relation to store data detected.", [], [], 0.75)

    # --- data question: check essential-slot ambiguity ---
    missing: List[str] = []
    questions: List[str] = []

    vague_top = re.search(r"\btop\b(?!\s*\d+)", ql) or re.search(r"\bbest\b(?!\s*\d+)", ql)
    # If the user already gave a concrete Top N anywhere (e.g. via clarification
    # "Top 5 ..."), don't flag the generic "top rows" boilerplate text.
    has_concrete_top = bool(re.search(r"\btop\s+\d+", ql))
    if vague_top and not has_concrete_top:
        missing.append("top_n")
        questions.append("How many top rows do you want (e.g. Top 5, Top 10)?")

    if re.search(r"\brecent\b", ql) and not re.search(r"\d{4}|last\s+\d+\s+(day|week|month)|q[1-4]|20\d{2}-\d{2}", ql):
        missing.append("date_range")
        questions.append(AMBIGUITY_QUESTIONS["date_range"])

    if re.search(r"\b(sales?|revenue|performance|doing)\b", ql) and not re.search(
            r"revenue|order|count|quantity|rating|payment|refund|discount|average|total|aov", ql):
        missing.append("metric")
        questions.append(AMBIGUITY_QUESTIONS["metric"])

    if re.search(r"\btrend\b|\bover time\b|\bcompare\b|\bbreakdown\b", ql) and not re.search(
            r"month|week|day|quarter|year|categor|country|product|segment|channel|method", ql):
        missing.append("grouping")
        questions.append(AMBIGUITY_QUESTIONS["grouping"])

    # pronoun without entity: "his orders", "its sales", "that product"
    if re.search(r"\b(his|her|its|their|that|those)\b.*\b(order|sale|product|customer)s?\b", ql):
        missing.append("entity")
        questions.append(AMBIGUITY_QUESTIONS["entity"].format(kind="customer/product"))

    # ultra-short data question
    if len(q.split()) <= 3 and not re.search(r"\d", q) and not re.search(
            r"revenue|sales|gmv|order|customer|product|payment|rating|review|refund|return", ql):
        missing.append("metric")
        if AMBIGUITY_QUESTIONS["metric"] not in questions:
            questions.append(AMBIGUITY_QUESTIONS["metric"])

    if missing:
        return Classification("ambiguous", f"Missing essential detail: {', '.join(missing)}.",
                              missing, questions[:3], 0.8)
    return Classification("in_scope", "Clear data question grounded in schema.", [], [], 0.85)
