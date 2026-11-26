"""Incident lifecycle, timeline events and evidence links."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.alerting import AlertSeverity
from app.models.base import Base, TimestampMixin, UUIDMixin, enum_column


class IncidentStatus(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    INVESTIGATING = "investigating"
    MITIGATING = "mitigating"
    MONITORING = "monitoring"
    RESOLVED = "resolved"
    CLOSED = "closed"


#: Allowed forward/backward transitions. Anything else is rejected server-side.
INCIDENT_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.OPEN: {IncidentStatus.ACKNOWLEDGED, IncidentStatus.INVESTIGATING},
    IncidentStatus.ACKNOWLEDGED: {IncidentStatus.INVESTIGATING, IncidentStatus.OPEN},
    IncidentStatus.INVESTIGATING: {
        IncidentStatus.MITIGATING,
        IncidentStatus.MONITORING,
        IncidentStatus.ACKNOWLEDGED,
    },
    IncidentStatus.MITIGATING: {IncidentStatus.MONITORING, IncidentStatus.INVESTIGATING},
    IncidentStatus.MONITORING: {
        IncidentStatus.RESOLVED,
        IncidentStatus.MITIGATING,
        IncidentStatus.INVESTIGATING,
    },
    IncidentStatus.RESOLVED: {IncidentStatus.CLOSED, IncidentStatus.MONITORING},
    IncidentStatus.CLOSED: set(),
}


class IncidentEventType(str, enum.Enum):
    CREATED = "created"
    STATUS_CHANGE = "status_change"
    ASSIGNMENT = "assignment"
    COMMENT = "comment"
    EVIDENCE_LINKED = "evidence_linked"
    AI_ANALYSIS = "ai_analysis"
    REPORT_EXPORTED = "report_exported"


class EvidenceKind(str, enum.Enum):
    LOG_EVENT = "log_event"
    HEALTH_CHECK_RESULT = "health_check_result"
    WEBHOOK_EVENT = "webhook_event"
    DEPLOYMENT = "deployment"
    EXTERNAL_URL = "external_url"
    NOTE = "note"


class Incident(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_workspace_status", "workspace_id", "status", "created_at"),
        Index("ix_incidents_workspace_severity", "workspace_id", "severity"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[IncidentStatus] = mapped_column(
        enum_column(IncidentStatus, "incident_status"), nullable=False, default=IncidentStatus.OPEN
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        enum_column(AlertSeverity, "incident_severity"),
        nullable=False,
        default=AlertSeverity.WARNING,
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    resolution_note: Mapped[str] = mapped_column(Text, default="", nullable=False)
    follow_up_actions: Mapped[list[dict]] = mapped_column(JSON, default=list, nullable=False)


class IncidentEvent(UUIDMixin, Base):
    __tablename__ = "incident_events"
    __table_args__ = (Index("ix_incident_events_incident_time", "incident_id", "created_at"),)

    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    event_type: Mapped[IncidentEventType] = mapped_column(
        enum_column(IncidentEventType, "incident_event_type"), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_label: Mapped[str] = mapped_column(String(160), default="system", nullable=False)
    message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    from_status: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    to_status: Mapped[str] = mapped_column(String(40), default="", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)


class EvidenceLink(UUIDMixin, Base):
    __tablename__ = "evidence_links"
    __table_args__ = (
        Index("ix_evidence_incident_time", "incident_id", "created_at"),
        Index("ix_evidence_workspace", "workspace_id", "kind"),
    )

    incident_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[EvidenceKind] = mapped_column(enum_column(EvidenceKind, "evidence_kind"), nullable=False)
    ref_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    url: Mapped[str] = mapped_column(String(2048), default="", nullable=False)
    title: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    excerpt: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    added_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)


__all__ = [
    "IncidentStatus",
    "INCIDENT_TRANSITIONS",
    "IncidentEventType",
    "EvidenceKind",
    "Incident",
    "IncidentEvent",
    "EvidenceLink",
]
