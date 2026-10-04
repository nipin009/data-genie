"""Pydantic API schemas."""
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    conversation_id: Optional[str] = None


class ClarifyRequest(BaseModel):
    conversation_id: str
    answers: str = Field(..., min_length=1, max_length=2000)


class ChartSpec(BaseModel):
    type: str = "table"
    x: Optional[str] = None
    y: Optional[str] = None
    reason: Optional[str] = None


class ChatResponse(BaseModel):
    conversation_id: str
    classification: str
    answer: str
    sql: Optional[str] = None
    columns: List[str] = []
    rows: List[Dict[str, Any]] = []
    row_count: int = 0
    truncated: bool = False
    chart: ChartSpec = ChartSpec()
    clarification_questions: List[str] = []
    selected_tables: List[str] = []
    validation_error: Optional[str] = None


class HistoryMessage(BaseModel):
    role: str
    content: str
    metadata: Optional[Dict[str, Any]] = None


class ConversationHistory(BaseModel):
    conversation_id: str
    messages: List[HistoryMessage]


class MutationPreviewRequest(BaseModel):
    instruction: str = Field(..., min_length=3, max_length=4000)


class MutationPreviewResponse(BaseModel):
    proposal_id: str
    instruction: str
    sql: str
    summary: str
    risk: str
    expires_at: str


class MutationConfirmRequest(BaseModel):
    proposal_id: str
    confirmation: str = Field(..., description="Must exactly equal APPLY")


class MutationConfirmResponse(BaseModel):
    proposal_id: str
    status: str
    rows_affected: Optional[int] = None
    message: str
