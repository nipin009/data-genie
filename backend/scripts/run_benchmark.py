"""Benchmark runner: executes benchmark/questions.yaml through the LangGraph
workflow against the live DB and reports accuracy/latency/grounding.

Usage: python -m scripts.run_benchmark [--database-url ...] [--output results.json]
"""
import argparse
import json
import os
import sys
import tempfile
import time

import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.db import reset_engine  # noqa: E402
from app.graph import reset_schema_cache, run_question  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=None)
    ap.add_argument("--output", default="benchmark_results.json")
    ap.add_argument("--questions-file", default=None, help="Optional YAML corpus, e.g. benchmark/evaluation_questions.yaml")
    ap.add_argument("--seed", action="store_true",
                    help="Seed the target database before running (recreates only dg_-prefixed tables).")
    ap.add_argument("--temporary-sqlite", action="store_true",
                    help="Run against a disposable seeded SQLite database; useful for CI and local checks.")
    args = ap.parse_args()
    temporary_db = None
    if args.temporary_sqlite:
        temporary_db = tempfile.TemporaryDirectory(prefix="data-genie-benchmark-")
        args.database_url = f"sqlite:///{os.path.join(temporary_db.name, 'benchmark.db')}"
        args.seed = True
    if args.seed and not args.database_url:
        ap.error("--seed requires --database-url, or use --temporary-sqlite")
    if args.database_url:
        os.environ["DATABASE_URL"] = args.database_url
        from app.config import get_settings  # noqa: E402
        get_settings.cache_clear()
        reset_engine()
        reset_schema_cache()
    if args.seed:
        from scripts.seed_db import run as seed_database  # noqa: E402
        seed_database(db_url=args.database_url)
        reset_engine()
        reset_schema_cache()

    corpus = args.questions_file or os.path.join(os.path.dirname(__file__), "..", "benchmark", "questions.yaml")
    with open(corpus) as f:
        bench = yaml.safe_load(f)

    results = []
    for item in bench["questions"]:
        q = item["question"]
        t0 = time.time()
        try:
            out = run_question(q, [])
            latency = round(time.time() - t0, 3)
            expected_class = item.get("expect_class")
            ok_class = out.get("classification") == expected_class if expected_class is not None else None
            expect_rows = item.get("expect_rows")
            rows_ok = None
            if expect_rows == "none":
                rows_ok = out.get("row_count", 0) == 0 or out.get("classification") in ("ambiguous", "unrelated", "unsupported")
            elif expect_rows == "some":
                rows_ok = out.get("row_count", 0) > 0 or out.get("classification") == "ambiguous"
            sql_low = (out.get("sql") or "").lower()
            required = [x.lower() for x in item.get("expect_sql_all", [])]
            alternatives = [[x.lower() for x in group] for group in item.get("expect_sql_any", [])]
            sql_scored = bool(required or alternatives)
            sql_ok = (all(x in sql_low for x in required) and all(any(x in sql_low for x in group) for group in alternatives)) if sql_scored else None
            # Non-SQL routes have no SQL contract to assert.
            if expected_class in ("ambiguous", "unrelated", "unsupported", "not_in_schema"):
                sql_ok = not bool(out.get("sql"))
                sql_scored = True
            scored = ok_class is not None and rows_ok is not None and sql_ok is not None
            results.append({"id": item["id"], "question": q, "pass_class": ok_class,
                            "pass_rows": rows_ok, "pass_sql": sql_ok, "scored": scored,
                            "classification": out.get("classification"),
                            "execution_success": bool(out.get("sql")) and not bool(out.get("validation_error")),
                            "expected_sql_task": expected_class == "in_scope",
                            "row_count": out.get("row_count"), "chart": (out.get("chart") or {}).get("type"),
                            "sql": (out.get("sql") or "")[:300], "latency_s": latency,
                            "category": item.get("category")})
        except Exception as e:
            results.append({"id": item["id"], "question": q, "error": str(e), "pass_class": False, "pass_rows": False})
    n = len(results)
    def score_rate(field):
        scored = [r[field] for r in results if r.get(field) is not None]
        return round(sum(bool(x) for x in scored) / len(scored), 3) if scored else None

    def score_rate_for_category(rows):
        scored = [r["pass_class"] for r in rows if r.get("pass_class") is not None]
        return round(sum(bool(x) for x in scored) / len(scored), 3) if scored else None

    pc, pr, ps = score_rate("pass_class"), score_rate("pass_rows"), score_rate("pass_sql")
    expected_sql_tasks = [r for r in results if r.get("expected_sql_task")]
    execution = (round(sum(bool(r.get("execution_success")) for r in expected_sql_tasks) /
                       len(expected_sql_tasks), 3) if expected_sql_tasks else None)
    clarification = [r for r in results if r.get("category") in ("clarify", "ambiguity")]
    irrelevant = [r for r in results if r.get("category") == "irrelevant"]
    summary = {"total": n, "fully_scored_cases": sum(r["scored"] for r in results),
               "class_accuracy": pc, "rows_ok_rate": pr,
               "sql_contract_rate": ps, "sql_validity_rate": ps,
               "execution_success_rate": execution, "execution_scored_cases": len(expected_sql_tasks),
               "clarification_accuracy": score_rate_for_category(clarification),
               "irrelevant_handling_accuracy": score_rate_for_category(irrelevant),
               "avg_latency_s": round(sum(r.get("latency_s", 0) for r in results) / max(n, 1), 3)}
    print(json.dumps(summary, indent=2))
    for r in results:
        flag = "UNSCORED" if not r["scored"] else ("PASS" if (r.get("pass_class") and r.get("pass_rows") and r.get("pass_sql")) else "FAIL")
        print(f"[{flag}] {r['id']} ({r.get('category')}) class={r.get('classification')} rows={r.get('row_count')} {r.get('latency_s', '?')}s")
        print(f"      Q: {r['question']}")
    with open(args.output, "w") as f:
        json.dump({"summary": summary, "results": results}, f, indent=2)
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
