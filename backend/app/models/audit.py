"""Audit trail for security- and operations-sensitive actions."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDMixin


class AuditEvent(UUIDMixin, Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_workspace_time", "workspace_id", "created_at"),
        Index("ix_audit_workspace_action", "workspace_id", "action"),
        Index("ix_audit_actor", "actor_id", "created_at"),
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=True, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_email: Mapped[str] = mapped_column(String(320), default="", nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    target_type: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    outcome: Mapped[str] = mapped_column(String(40), default="success", nullable=False)
    request_id: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)


__all__ = ["AuditEvent"]
