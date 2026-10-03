"""Automatic visualization selection from query results.

Rules (deterministic, explainable):
- 1 row x 1-3 numeric cols -> KPI "table" w/ single-row highlight (use table).
- time-like first col (YYYY-MM / date) + numeric -> line.
- 2 cols [label, numeric], 2-12 rows -> bar; >12 rows -> table w/ bar option.
- 2 cols [label, numeric], 2-7 rows + share semantics -> pie (also offer bar).
- >=3 cols or >50 rows -> table.
- otherwise table.

Returns a ChartSpec dict consumed by the frontend (Recharts).
"""
from typing import Dict, List
import re

DATE_LIKE = re.compile(r"^(\d{4}-\d{2}(-\d{2})?|\d{4}/Q[1-4]|Q[1-4]|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", re.I)


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _numeric_cols(columns: List[str], rows: List[Dict]) -> List[str]:
    if not rows:
        return []
    num = []
    for c in columns:
        vals = [r.get(c) for r in rows[:20] if r.get(c) is not None]
        if vals and all(_is_number(v) for v in vals):
            num.append(c)
    return num


def choose_chart(columns: List[str], rows: List[Dict], question: str = "") -> Dict:
    q = (question or "").lower()
    n_rows, n_cols = len(rows), len(columns)
    if n_rows == 0 or n_cols == 0:
        return {"type": "table", "x": None, "y": None, "reason": "No data to visualize."}
    numeric = _numeric_cols(columns, rows)
    first_vals = [str(r.get(columns[0], "")) for r in rows[:10]]
    looks_time = any(DATE_LIKE.search(v or "") for v in first_vals) or columns[0].lower() in (
        "month", "week", "day", "date", "quarter", "order_date", "payment_date", "review_date", "order_month")

    if n_rows == 1 and len(numeric) >= 1:
        return {"type": "table", "x": columns[0], "y": numeric[0] if numeric else None,
                "reason": "Single summary row is best as a KPI table."}
    if looks_time and numeric:
        y = numeric[0]
        if "revenue" in " ".join(numeric).lower() or "revenue" in q:
            y = next((c for c in numeric if "revenue" in c.lower() or "total" in c.lower()), y)
        return {"type": "line", "x": columns[0], "y": y, "reason": "Time-ordered numeric series suits a line chart."}
    if n_cols == 2 and len(numeric) == 1:
        if 2 <= n_rows <= 12:
            if n_rows <= 7 and any(w in q for w in ("share", "breakdown", "proportion", "percent", "distribution", "pie")):
                return {"type": "pie", "x": columns[0], "y": numeric[0],
                        "reason": "Small part-to-whole breakdown suits a pie chart."}
            return {"type": "bar", "x": columns[0], "y": numeric[0],
                    "reason": "Label/value pairs suit a bar chart."}
        return {"type": "table", "x": columns[0], "y": numeric[0],
                "reason": f"{n_rows} categories is too many for a readable chart; showing a table."}
    if n_cols >= 2 and len(numeric) >= 1 and 2 <= n_rows <= 15 and not looks_time:
        return {"type": "bar", "x": columns[0], "y": numeric[0],
                "reason": "Categorical comparison suits a bar chart."}
    return {"type": "table", "x": None, "y": None, "reason": "Wide/multi-column result is best explored as a table."}
