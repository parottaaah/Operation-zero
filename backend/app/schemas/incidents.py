"""Incident, timeline, evidence and report schemas."""

from __future__ import annotations

import uuid

from pydantic import Field

from app.models.alerting import AlertSeverity
from app.models.incident import EvidenceKind, IncidentEventType, IncidentStatus
from app.schemas.common import APIModel, UtcDateTime


class FollowUpAction(APIModel):
    text: str = Field(min_length=1, max_length=500)
    owner: str = Field(default="", max_length=200)
    done: bool = False


class IncidentCreate(APIModel):
    title: str = Field(min_length=3, max_length=240)
    summary: str = Field(default="", max_length=8000)
    severity: AlertSeverity = AlertSeverity.WARNING
    service_id: uuid.UUID | None = None
    owner_id: uuid.UUID | None = None


class IncidentUpdate(APIModel):
    title: str | None = Field(default=None, min_length=3, max_length=240)
    summary: str | None = Field(default=None, max_length=8000)
    severity: AlertSeverity | None = None
    status: IncidentStatus | None = None
    owner_id: uuid.UUID | None = None
    clear_owner: bool = False
    resolution_note: str | None = Field(default=None, max_length=8000)
    follow_up_actions: list[FollowUpAction] | None = None
    comment: str | None = Field(default=None, max_length=10_000)


class IncidentEventOut(APIModel):
    id: uuid.UUID
    event_type: IncidentEventType
    actor_id: uuid.UUID | None
    actor_label: str
    message: str
    from_status: str
    to_status: str
    metadata_json: dict
    created_at: UtcDateTime


class EvidenceLinkCreate(APIModel):
    kind: EvidenceKind
    ref_id: uuid.UUID | None = None
    url: str = Field(default="", max_length=2048)
    title: str = Field(default="", max_length=240)
    excerpt: str = Field(default="", max_length=10_000)
    metadata: dict = Field(default_factory=dict)


class EvidenceLinkOut(APIModel):
    id: uuid.UUID
    kind: EvidenceKind
    ref_id: uuid.UUID | None
    url: str
    title: str
    excerpt: str
    metadata_json: dict
    added_by_id: uuid.UUID | None
    created_at: UtcDateTime


class IncidentSummaryOut(APIModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    title: str
    status: IncidentStatus
    severity: AlertSeverity
    service_id: uuid.UUID | None
    service_name: str | None = None
    owner_id: uuid.UUID | None
    owner_label: str | None = None
    detected_at: UtcDateTime
    resolved_at: UtcDateTime | None
    closed_at: UtcDateTime | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class AIAnalysisBrief(APIModel):
    id: uuid.UUID
    status: str
    provider: str
    model_id: str
    created_at: UtcDateTime
    feedback: str | None = None


class IncidentDetailOut(IncidentSummaryOut):
    summary: str
    resolution_note: str
    follow_up_actions: list[dict]
    acknowledged_at: UtcDateTime | None
    events: list[IncidentEventOut]
    evidence: list[EvidenceLinkOut]
    alert_ids: list[uuid.UUID]
    ai_analyses: list[AIAnalysisBrief]


class IncidentCommentCreate(APIModel):
    message: str = Field(min_length=1, max_length=10_000)


class ReportOut(APIModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    format: str
    filename: str
    size_bytes: int
    redaction_level: str
    generated_at: UtcDateTime


__all__ = [
    "FollowUpAction",
    "IncidentCreate",
    "IncidentUpdate",
    "IncidentEventOut",
    "EvidenceLinkCreate",
    "EvidenceLinkOut",
    "IncidentSummaryOut",
    "IncidentDetailOut",
    "IncidentCommentCreate",
    "AIAnalysisBrief",
    "ReportOut",
]
