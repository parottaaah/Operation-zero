"""AI analysis schemas."""

from __future__ import annotations

import uuid

from pydantic import Field

from app.schemas.common import APIModel, UtcDateTime


class AIAnalysisRequest(APIModel):
    focus: str = Field(default="", max_length=500, description="Optional investigator focus")


class AIFeedbackRequest(APIModel):
    feedback: str = Field(description="accepted | edited | rejected")
    note: str = Field(default="", max_length=2000)


class AIAnalysisOut(APIModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    status: str
    provider: str
    model_id: str
    prompt_version: str
    evidence_ids: list[str]
    output: dict
    citation_count: int
    invalid_citations: list[str]
    latency_ms: float | None
    error: str
    feedback: str | None
    feedback_note: str
    requested_by_id: uuid.UUID | None
    created_at: UtcDateTime


__all__ = ["AIAnalysisRequest", "AIFeedbackRequest", "AIAnalysisOut"]
