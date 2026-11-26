"""Evidence-grounded AI analyses (read-only, human-reviewed)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, enum_column


class AIAnalysisStatus(str, enum.Enum):
    COMPLETED = "completed"
    FAILED = "failed"


class AIFeedback(str, enum.Enum):
    ACCEPTED = "accepted"
    EDITED = "edited"
    REJECTED = "rejected"


class AIAnalysis(UUIDMixin, Base):
    __tablename__ = "ai_analyses"
    __table_args__ = (Index("ix_ai_incident_time", "incident_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    requested_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[AIAnalysisStatus] = mapped_column(
        enum_column(AIAnalysisStatus, "ai_analysis_status"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    model_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    output: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    citation_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    invalid_citations: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    feedback: Mapped[AIFeedback | None] = mapped_column(enum_column(AIFeedback, "ai_feedback"), nullable=True)
    feedback_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    feedback_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)


__all__ = ["AIAnalysisStatus", "AIFeedback", "AIAnalysis"]
