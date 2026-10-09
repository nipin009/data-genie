"""FastAPI entrypoint: chat, clarify, history, health, schema endpoints.

- POST /api/chat            -> full JSON answer (runs LangGraph workflow)
- POST /api/chat/stream     -> SSE streaming (status events + final payload)
- POST /api/clarify         -> answer pending clarification questions, re-runs workflow
- GET  /api/history/{id}    -> conversation history
- GET  /api/schema          -> live introspected schema (tables, FK graph)
- GET  /healthz             -> health
"""
import json
import time
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from . import conversation_store as store
from .auth import require_role
from .config import get_settings
from .graph import get_schema_snapshot, run_question
from .logging_config import log, setup_logging
from .schemas import (ChatRequest, ChatResponse, ChartSpec, ClarifyRequest, ConversationHistory,
                      MutationPreviewRequest, MutationPreviewResponse, MutationConfirmRequest, MutationConfirmResponse)

settings = get_settings()
setup_logging(settings.LOG_LEVEL)

app = FastAPI(title="Data Genie — Text-to-SQL", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=list({settings.FRONTEND_ORIGIN, "http://localhost:3000", "http://127.0.0.1:3000"}),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def api_auth(request, call_next):
    """Protect data APIs while keeping health checks available to orchestrators."""
    if request.url.path in {"/healthz", "/readyz"}:
        return await call_next(request)
    try:
        roles = ("admin",) if request.url.path.startswith("/api/dashboard") else ("analyst", "admin")
        request.state.role = await require_role(request, *roles)
    except HTTPException as exc:
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail}, headers=exc.headers or {})
    return await call_next(request)


def _to_response(cid: str, result: dict) -> ChatResponse:
    chart = result.get("chart") or {"type": "table"}
    return ChatResponse(
        conversation_id=cid,
        classification=result.get("classification") or "in_scope",
        answer=result.get("answer") or "",
        sql=result.get("sql"),
        columns=result.get("columns") or [],
        rows=result.get("rows") or [],
        row_count=result.get("row_count") or 0,
        truncated=bool(result.get("truncated")),
        chart=ChartSpec(type=chart.get("type", "table"), x=chart.get("x"),
                        y=chart.get("y"), reason=chart.get("reason")),
        clarification_questions=result.get("clarification_questions") or [],
        selected_tables=result.get("selected_tables") or [],
        validation_error=result.get("validation_error"),
    )


def _audit(cid: str, request_text: str, result: Optional[dict], started: float, error: Optional[str] = None) -> None:
    """Audit failures must never make an otherwise valid chat response fail."""
    try:
        store.log_request(cid, request_text, result, round((time.perf_counter() - started) * 1000), error)
    except Exception:
        log.exception("request audit logging failed")


def _clarification_prompt(original_question: str, questions: list[str], prior_answers: str, new_answers: str) -> str:
    """Build stable context for a follow-up without recursively nesting prompts."""
    parts = [f"Original request: {original_question}"]
    if prior_answers:
        parts.append(f"Earlier clarification: {prior_answers}")
    if questions:
        parts.append("Outstanding questions: " + "; ".join(questions))
    parts.append(f"User clarification: {new_answers}")
    return "\n".join(parts)


@app.get("/healthz")
def healthz():
    runtime = get_settings()
    from .llm import has_llm_runtime
    return {
        "status": "ok",
        "llm_configured": bool(runtime.GOOGLE_API_KEY),
        "llm_runtime_available": has_llm_runtime(),
        "offline_fallback_enabled": runtime.ALLOW_DETERMINISTIC_FALLBACK,
    }


@app.get("/readyz")
def readyz():
    """Expose the otherwise confusing no-LLM state before a user sends a query."""
    runtime = get_settings()
    from .llm import has_llm_runtime
    if not has_llm_runtime() and not runtime.ALLOW_DETERMINISTIC_FALLBACK:
        raise HTTPException(
            503,
            "Text-to-SQL is not configured. Set GOOGLE_API_KEY and install langchain-google-genai, or enable the limited deterministic fallback for demo use.",
        )
    return {"status": "ready", "mode": "llm" if has_llm_runtime() else "limited_offline"}


def _require_mutation_admin(request) -> None:
    """Writes are opt-in and require real API-key admin authentication."""
    if not settings.ENABLE_MUTATIONS:
        raise HTTPException(403, "Mutations are disabled. Set ENABLE_MUTATIONS=true to enable the reviewed admin workflow.")
    if not settings.AUTH_ENABLED or getattr(request.state, "role", None) != "admin":
        raise HTTPException(403, "Mutations require AUTH_ENABLED=true and an admin X-API-Key.")


@app.post("/api/admin/mutations/preview", response_model=MutationPreviewResponse)
def preview_mutation(req: MutationPreviewRequest, request):
    """Generate and validate a mutation proposal; it does not execute SQL."""
    _require_mutation_admin(request)
    from .mutations import preview_mutation as build_preview
    try:
        proposal = build_preview(req.instruction)
        return MutationPreviewResponse(proposal_id=proposal.proposal_id, instruction=proposal.instruction,
                                       sql=proposal.sql, summary=proposal.summary, risk=proposal.risk,
                                       expires_at=proposal.expires_at.isoformat())
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/admin/mutations/confirm", response_model=MutationConfirmResponse)
def confirm_mutation(req: MutationConfirmRequest, request):
    """Apply exactly one previously reviewed proposal after explicit approval."""
    _require_mutation_admin(request)
    from .mutations import apply_mutation
    try:
        proposal = apply_mutation(req.proposal_id, req.confirmation)
        reset_schema_cache()
        return MutationConfirmResponse(proposal_id=proposal.proposal_id, status=proposal.status,
                                       rows_affected=getattr(proposal, "rows_affected", None),
                                       message="Mutation applied after explicit admin confirmation.")
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/schema")
def api_schema():
    try:
        snap = get_schema_snapshot()
        return {
            "tables": {t: {"columns": [c.name for c in info.columns],
                           "primary_keys": info.primary_keys,
                           "foreign_keys": info.foreign_keys,
                           "row_count": info.row_count}
                       for t, info in snap.tables.items()},
            "join_edges": [{"from_table": a, "from_col": b, "to_table": c, "to_col": d}
                           for a, b, c, d in snap.join_edges],
        }
    except Exception as e:
        log.exception("schema endpoint failed")
        raise HTTPException(500, f"schema introspection failed: {e}")


@app.get("/api/dashboard/sessions")
def dashboard_sessions(limit: int = Query(50, ge=1, le=200)):
    return {"sessions": store.dashboard_sessions(limit)}


@app.get("/api/dashboard/logs")
def dashboard_logs(limit: int = Query(100, ge=1, le=500)):
    return {"logs": store.dashboard_logs(limit)}


@app.get("/api/dashboard/metrics")
def dashboard_metrics(limit: int = Query(1000, ge=1, le=5000)):
    """Aggregated request health for the admin operations dashboard."""
    return store.dashboard_metrics(limit)


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    started = time.perf_counter()
    cid = store.get_or_create(req.conversation_id)
    hist = store.history(cid)
    # If a clarification was pending and user replies, merge context.
    pending = store.pop_pending(cid)
    question = req.message
    if pending.get("questions"):
        question = _clarification_prompt(pending.get("original_question", ""), pending["questions"],
                                         pending.get("clarification_context", ""), req.message)
    store.append(cid, "user", req.message)
    try:
        result = run_question(question, hist)
    except Exception as e:
        log.exception("workflow failed")
        _audit(cid, req.message, None, started, str(e))
        raise HTTPException(500, f"workflow failed: {e}")
    if result.get("classification") == "ambiguous":
        store.set_pending(cid, result.get("clarification_questions", []),
                          pending.get("original_question") or req.message, result.get("query_spec"),
                          pending.get("clarification_context", "") + ("\n" if pending.get("clarification_context") else "") + req.message)
    store.append(cid, "assistant", result.get("answer", ""), result)
    _audit(cid, req.message, result, started)
    return _to_response(cid, result)


@app.post("/api/clarify", response_model=ChatResponse)
def clarify(req: ClarifyRequest):
    started = time.perf_counter()
    cid = store.get_or_create(req.conversation_id)
    pending = store.pop_pending(cid)
    hist = store.history(cid)
    combined = (_clarification_prompt(pending.get("original_question", ""), pending.get("questions", []),
                                      pending.get("clarification_context", ""), req.answers)
                if pending.get("questions") else req.answers)
    store.append(cid, "user", req.answers)
    try:
        result = run_question(combined, hist)
    except Exception as e:
        log.exception("clarify workflow failed")
        _audit(cid, req.answers, None, started, str(e))
        raise HTTPException(500, f"workflow failed: {e}")
    if result.get("classification") == "ambiguous":
        prior = pending.get("clarification_context", "")
        all_answers = prior + ("\n" if prior else "") + req.answers
        store.set_pending(cid, result.get("clarification_questions", []),
                          pending.get("original_question", ""), result.get("query_spec"), all_answers)
    store.append(cid, "assistant", result.get("answer", ""), result)
    _audit(cid, req.answers, result, started)
    return _to_response(cid, result)


@app.get("/api/history/{cid}", response_model=ConversationHistory)
def get_history(cid: str):
    return ConversationHistory(conversation_id=cid,
                               messages=store.history(cid))


@app.post("/api/chat/stream")
def chat_stream(req: ChatRequest):
    started = time.perf_counter()
    cid = store.get_or_create(req.conversation_id)
    hist = store.history(cid)
    pending = store.pop_pending(cid)
    question = (_clarification_prompt(pending.get("original_question", ""), pending.get("questions", []),
                                      pending.get("clarification_context", ""), req.message)
                if pending.get("questions") else req.message)
    store.append(cid, "user", req.message)

    def event_stream() -> AsyncIterator[str]:
        def send(evt: str, data: dict) -> str:
            return f"event: {evt}\ndata: {json.dumps(data)}\n\n"
        yield send("status", {"stage": "classifying"})
        try:
            result = run_question(question, hist)
        except Exception as e:
            log.exception("stream workflow failed")
            _audit(cid, req.message, None, started, str(e))
            yield send("error", {"message": str(e)})
            return
        if result.get("classification") == "ambiguous":
            prior = pending.get("clarification_context", "")
            all_answers = prior + ("\n" if prior else "") + req.message
            store.set_pending(cid, result.get("clarification_questions", []),
                              pending.get("original_question") or req.message,
                              result.get("query_spec"), all_answers)
            yield send("status", {"stage": "clarification_needed"})
        else:
            yield send("status", {"stage": "answering"})
        store.append(cid, "assistant", result.get("answer", ""), result)
        _audit(cid, req.message, result, started)
        resp = _to_response(cid, result).model_dump()
        yield send("final", resp)

    return StreamingResponse(event_stream(), media_type="text/event-stream")
