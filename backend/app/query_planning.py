"""Structured planning before SQL generation.

The LLM is asked for a typed representation of the request, not SQL, before
the SQL-generation call.  The deterministic QuerySpec parser remains a safe
offline fallback, while the structured plan broadens language coverage when a
Gemini key is configured.
"""
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from .config import get_settings
from .query_spec import FilterSpec, QuerySpec, build_query_spec


class PlannedFilter(BaseModel):
    field: str = Field(description="Business field or user concept to filter")
    operator: str = Field(default="equals", description="equals, contains, between, before, after, or in")
    value: Any = Field(default=None, description="Literal value from the request")
    end_value: Any = Field(default=None, description="Exclusive end for a between range when supplied")


class StructuredQueryPlan(BaseModel):
    metrics: List[str] = Field(default_factory=list)
    dimensions: List[str] = Field(default_factory=list)
    filters: List[PlannedFilter] = Field(default_factory=list)
    required_outputs: List[str] = Field(default_factory=list)
    top_n: Optional[int] = Field(default=None, ge=1, le=500)
    sort_direction: Optional[str] = Field(default=None, pattern="^(asc|desc)$")


def plan_question(question: str, schema_context: str) -> Optional[StructuredQueryPlan]:
    """Ask Gemini for a schema-grounded plan using structured output.

    A planning failure is intentionally non-fatal: deterministic parsing and
    the downstream SQL guardrails still apply, which keeps offline operation
    and model-outage behavior safe.
    """
    if not get_settings().GOOGLE_API_KEY:
        return None
    try:
        from .llm import generate_structured, has_llm_runtime
        if not has_llm_runtime():
            return None
        prompt = f"""Extract a precise analytics query plan. Do not create SQL.
Use only concepts that can be supported by the supplied schema. Preserve every
explicit filter, requested output, grouping, ranking, and date expression.
If a phrase names a business value (for example Books or Germany), put it in a
filter instead of dropping it. Use asc or desc only when explicitly implied.

Schema context:
{schema_context}

Question: {question}"""
        return generate_structured(prompt, StructuredQueryPlan)
    except Exception:
        return None


def build_planned_query_spec(question: str, plan: Optional[StructuredQueryPlan]) -> QuerySpec:
    """Merge an LLM plan into deterministic requirements without weakening them."""
    spec = build_query_spec(question)
    if not plan:
        return spec
    for metric in plan.metrics:
        if metric and metric not in spec.metrics:
            spec.metrics.append(metric)
    for dimension in plan.dimensions:
        if dimension and dimension not in spec.dimensions:
            spec.dimensions.append(dimension)
    for output in plan.required_outputs:
        if output and output not in spec.required_outputs:
            spec.required_outputs.append(output)
    known = {(f.field, str(f.value), str(f.end_value)) for f in spec.filters}
    for item in plan.filters:
        key = (item.field, str(item.value), str(item.end_value))
        if item.field and key not in known:
            spec.filters.append(FilterSpec(item.field, item.operator, item.value,
                                           end_value=item.end_value, source="structured_plan"))
            known.add(key)
    if plan.top_n is not None:
        spec.top_n = plan.top_n
    if plan.sort_direction:
        spec.sort_direction = plan.sort_direction
    return spec
