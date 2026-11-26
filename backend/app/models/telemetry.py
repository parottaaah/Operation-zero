"""Structured telemetry: LogEvent (redacted before persistence)."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin, enum_column


class Severity(str, enum.Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogEvent(UUIDMixin, Base):
    __tablename__ = "log_events"
    __table_args__ = (
        Index("ix_logs_workspace_ts", "workspace_id", "event_timestamp"),
        Index("ix_logs_workspace_service_ts", "workspace_id", "service_id", "event_timestamp"),
        Index("ix_logs_workspace_severity_ts", "workspace_id", "severity", "event_timestamp"),
        UniqueConstraint("workspace_id", "idempotency_key", name="uq_logs_workspace_idempotency_key"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True
    )
    environment: Mapped[str] = mapped_column(String(40), default="production", nullable=False)
    severity: Mapped[Severity] = mapped_column(
        enum_column(Severity, "severity"), nullable=False, default=Severity.INFO
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    event_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    attributes: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    redaction_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    redacted_fields: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ingest_source: Mapped[str] = mapped_column(String(40), default="api", nullable=False)
    payload_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


__all__ = ["Severity", "LogEvent"]
