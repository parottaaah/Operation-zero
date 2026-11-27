"""Platform-support entities: notifications, idempotency records, generated reports."""

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

from app.models.base import Base, TimestampMixin, UUIDMixin, enum_column


class NotificationStatus(str, enum.Enum):
    QUEUED = "queued"
    SENT = "sent"
    FAILED = "failed"


class Notification(UUIDMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_workspace_time", "workspace_id", "created_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(20), default="in_app", nullable=False)
    subject: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    related_type: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    related_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(
        enum_column(NotificationStatus, "notification_status"),
        nullable=False,
        default=NotificationStatus.QUEUED,
    )
    error: Mapped[str] = mapped_column(String(400), default="", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class IdempotencyKey(UUIDMixin, Base):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),
        Index("ix_idempotency_expires", "expires_at"),
    )

    scope: Mapped[str] = mapped_column(String(80), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    response_status: Mapped[int] = mapped_column(Integer, default=200, nullable=False)
    response_body: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)


class WorkerDeadLetter(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "worker_dead_letters"
    __table_args__ = (
        UniqueConstraint("job_type", "job_id", name="uq_worker_dead_letter_job"),
        Index("ix_worker_dead_letter_workspace_time", "workspace_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    job_type: Mapped[str] = mapped_column(String(40), nullable=False)
    job_id: Mapped[str] = mapped_column(String(64), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    last_error: Mapped[str] = mapped_column(String(1000), default="", nullable=False)


class Report(UUIDMixin, Base):
    __tablename__ = "reports"
    __table_args__ = (Index("ix_reports_workspace_time", "workspace_id", "generated_at"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fmt: Mapped[str] = mapped_column("format", String(10), nullable=False)
    filename: Mapped[str] = mapped_column(String(240), nullable=False)
    object_key: Mapped[str] = mapped_column(String(400), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    redaction_level: Mapped[str] = mapped_column(String(40), default="standard", nullable=False)
    generated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)


__all__ = [
    "NotificationStatus",
    "Notification",
    "IdempotencyKey",
    "Report",
    "WorkerDeadLetter",
]
