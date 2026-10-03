"""Natural-language answers strictly grounded in DB results.

Never invents numbers: every figure is extracted from rows. Handles empty
results, single KPIs, grouped breakdowns, and row listings.
"""
from typing import Dict, List, Optional


def _fmt(v) -> str:
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, int):
        return f"{v:,}"
    return str(v)


def grounded_answer(question: str, columns: List[str], rows: List[Dict], chart: Optional[Dict] = None) -> str:
    n = len(rows)
    if n == 0:
        return ("I found no matching data for that question. Try widening the date range, "
                "removing a filter, or checking the spelling of names.")
    if n == 1 and len(columns) <= 4:
        parts = ", ".join(f"{c} = {_fmt(r)}" for c, r in zip(columns, [rows[0][c] for c in columns]))
        return f"Based on the database, the result is: {parts}."
    # time series
    if chart and chart.get("type") == "line" and len(columns) >= 2:
        x, y = columns[0], chart.get("y") or columns[1]
        first, last = rows[0], rows[-1]
        peak = max(rows, key=lambda r: (r.get(y) or 0) if isinstance(r.get(y), (int, float)) else 0)
        return (f"Based on {n} time periods in the database: {y} went from {_fmt(first.get(y))} "
                f"({first.get(x)}) to {_fmt(last.get(y))} ({last.get(x)}), peaking at {_fmt(peak.get(y))} in {peak.get(x)}.")
    # categorical breakdown
    if len(columns) == 2 and n <= 20:
        top = rows[0]
        items = "; ".join(f"{r[columns[0]]}: {_fmt(r[columns[1]])}" for r in rows[:5])
        more = f" (+{n-5} more)" if n > 5 else ""
        return f"Based on {n} groups in the database, the top result is {top[columns[0]]} with {_fmt(top[columns[1]])} {columns[1]}. Breakdown: {items}{more}."
    # row listing
    shown = min(n, 5)
    head = "; ".join(
        "(" + ", ".join(f"{c}={_fmt(r[c])}" for c in columns[:4]) + ")" for r in rows[:shown])
    more = f" and {n - shown} more rows" if n > shown else ""
    return f"I found {n} matching rows in the database. First {shown}: {head}{more}."
