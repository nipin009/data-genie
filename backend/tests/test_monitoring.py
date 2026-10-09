from app.conversation_store import summarize_request_logs


def test_monitoring_summary_reports_failures_latency_and_classifications():
    summary = summarize_request_logs([
        {"status": "ok", "latency_ms": 10, "classification": "in_scope"},
        {"status": "error", "latency_ms": 30, "classification": "in_scope"},
        {"status": "ok", "latency_ms": 20, "classification": "ambiguous"},
    ])
    assert summary["window_requests"] == 3
    assert summary["successful_requests"] == 2
    assert summary["failed_requests"] == 1
    assert summary["failure_rate"] == 0.3333
    assert summary["avg_latency_ms"] == 20.0
    assert summary["p95_latency_ms"] == 30
    assert summary["classification_counts"] == {"ambiguous": 1, "in_scope": 2}


def test_monitoring_summary_handles_an_empty_window():
    assert summarize_request_logs([]) == {
        "window_requests": 0,
        "successful_requests": 0,
        "failed_requests": 0,
        "failure_rate": 0.0,
        "avg_latency_ms": None,
        "p95_latency_ms": None,
        "classification_counts": {},
    }
