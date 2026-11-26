"""Incident lifecycle: transitions, timeline, ownership, evidence and audit."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.errors import Conflict, NotFound, ValidationFailed
from app.models.alerting import Alert, AlertSeverity
from app.models.base import utcnow
from app.models.identity import User
from app.models.incident import (
    INCIDENT_TRANSITIONS,
    EvidenceKind,
    EvidenceLink,
    Incident,
    IncidentEvent,
    IncidentEventType,
    IncidentStatus,
)
from app.models.integration import WebhookEvent
from app.models.service import HealthCheckResult, Service
from app.models.telemetry import LogEvent
from app.services.audit import record_audit
from app.services.redaction import RedactionReport, redact_value

RESOLUTION_REQUIRED_STATUSES = {IncidentStatus.RESOLVED, IncidentStatus.CLOSED}


def _actor_label(user: User | None) -> str:
    return user.full_name or user.email if user else "system"


def add_timeline(
    session: Session,
    incident: Incident,
    *,
    event_type: IncidentEventType,
    actor: User | None,
    message: str = "",
    from_status: str = "",
    to_status: str = "",
    metadata: dict | None = None,
) -> IncidentEvent:
    event = IncidentEvent(
        incident_id=incident.id,
        workspace_id=incident.workspace_id,
        event_type=event_type,
        actor_id=actor.id if actor else None,
        actor_label=_actor_label(actor),
        message=message,
        from_status=from_status,
        to_status=to_status,
        metadata_json=metadata or {},
        created_at=utcnow(),
    )
    session.add(event)
    return event


def create_incident(
    session: Session,
    *,
    workspace_id: uuid.UUID,
    actor: User | None,
    title: str,
    summary: str = "",
    severity: AlertSeverity = AlertSeverity.WARNING,
    status: IncidentStatus = IncidentStatus.OPEN,
    service_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    detected_at: datetime | None = None,
    alert: Alert | None = None,
    request_id: str = "",
) -> Incident:
    if status is not IncidentStatus.OPEN:
        raise ValidationFailed("new incidents must start in the open state")
    now = utcnow()
    incident = Incident(
        workspace_id=workspace_id,
        title=title[:240],
        summary=summary,
        severity=severity,
        status=status,
        service_id=service_id,
        owner_id=owner_id,
        created_by_id=actor.id if actor else None,
        detected_at=detected_at or now,
    )
    session.add(incident)
    session.flush()

    add_timeline(
        session,
        incident,
        event_type=IncidentEventType.CREATED,
        actor=actor,
        message=f"Incident opened: {incident.title}",
        to_status=IncidentStatus.OPEN.value,
        metadata={"alert_id": str(alert.id)} if alert else {},
    )
    if owner_id:
        add_timeline(
            session,
            incident,
            event_type=IncidentEventType.ASSIGNMENT,
            actor=actor,
            message="Owner assigned at creation",
            metadata={"owner_id": str(owner_id)},
        )
    record_audit(
        session,
        action="incident.create",
        workspace_id=workspace_id,
        actor_id=actor.id if actor else None,
        actor_email=actor.email if actor else "",
        target_type="incident",
        target_id=incident.id,
        request_id=request_id,
        metadata={"alert_id": str(alert.id) if alert else None, "severity": severity.value},
    )
    return incident


def transition_incident(
    session: Session,
    incident: Incident,
    *,
    actor: User,
    new_status: IncidentStatus,
    message: str = "",
    resolution_note: str | None = None,
    follow_up_actions: list[dict] | None = None,
    request_id: str = "",
) -> Incident:
    if new_status is incident.status:
        raise Conflict("incident is already in that state")
    allowed = INCIDENT_TRANSITIONS.get(incident.status, set())
    if new_status not in allowed:
        raise Conflict(
            f"invalid incident transition {incident.status.value} -> {new_status.value}",
            details={"allowed": sorted(s.value for s in allowed)},
        )

    if new_status in RESOLUTION_REQUIRED_STATUSES:
        note = resolution_note if resolution_note is not None else incident.resolution_note
        if not note or len(note.strip()) < 10:
            raise ValidationFailed(
                "a resolution note of at least 10 characters is required to resolve an incident"
            )
        incident.resolution_note = note.strip()
        incident.resolved_at = incident.resolved_at or utcnow()
        if new_status is IncidentStatus.CLOSED:
            incident.closed_at = utcnow()

    if new_status is IncidentStatus.ACKNOWLEDGED:
        incident.acknowledged_at = incident.acknowledged_at or utcnow()
    if follow_up_actions is not None:
        incident.follow_up_actions = follow_up_actions

    previous = incident.status
    incident.status = new_status
    add_timeline(
        session,
        incident,
        event_type=IncidentEventType.STATUS_CHANGE,
        actor=actor,
        message=message or f"Status changed from {previous.value} to {new_status.value}",
        from_status=previous.value,
        to_status=new_status.value,
        metadata=(
            {"resolution_note": incident.resolution_note}
            if new_status in RESOLUTION_REQUIRED_STATUSES
            else {}
        ),
    )
    record_audit(
        session,
        action="incident.transition",
        workspace_id=incident.workspace_id,
        actor_id=actor.id,
        actor_email=actor.email,
        target_type="incident",
        target_id=incident.id,
        request_id=request_id,
        metadata={"from": previous.value, "to": new_status.value},
    )
    return incident


def assign_owner(
    session: Session, incident: Incident, *, actor: User, owner: User | None, request_id: str = ""
) -> Incident:
    previous = incident.owner_id
    incident.owner_id = owner.id if owner else None
    add_timeline(
        session,
        incident,
        event_type=IncidentEventType.ASSIGNMENT,
        actor=actor,
        message=f"Owner set to {_actor_label(owner)}" if owner else "Owner unassigned",
        metadata={"previous_owner_id": str(previous) if previous else None},
    )
    record_audit(
        session,
        action="incident.assign",
        workspace_id=incident.workspace_id,
        actor_id=actor.id,
        actor_email=actor.email,
        target_type="incident",
        target_id=incident.id,
        request_id=request_id,
        metadata={"owner_id": str(owner.id) if owner else None},
    )
    return incident


def add_comment(
    session: Session,
    incident: Incident,
    *,
    actor: User,
    message: str,
    request_id: str = "",
) -> IncidentEvent:
    if not message.strip():
        raise ValidationFailed("comment must not be empty")
    event = add_timeline(
        session,
        incident,
        event_type=IncidentEventType.COMMENT,
        actor=actor,
        message=message.strip()[:10_000],
    )
    record_audit(
        session,
        action="incident.comment",
        workspace_id=incident.workspace_id,
        actor_id=actor.id,
        actor_email=actor.email,
        target_type="incident",
        target_id=incident.id,
        request_id=request_id,
        metadata={"event_id": str(event.id)},
    )
    return event


_EVIDENCE_MODELS = {
    EvidenceKind.LOG_EVENT: (LogEvent, "log event"),
    EvidenceKind.HEALTH_CHECK_RESULT: (HealthCheckResult, "health check result"),
    EvidenceKind.WEBHOOK_EVENT: (WebhookEvent, "webhook event"),
}


def add_evidence(
    session: Session,
    incident: Incident,
    *,
    actor: User,
    kind: EvidenceKind,
    ref_id: uuid.UUID | None = None,
    url: str = "",
    title: str = "",
    excerpt: str = "",
    metadata: dict | None = None,
    request_id: str = "",
) -> EvidenceLink:
    if kind in _EVIDENCE_MODELS:
        model, label = _EVIDENCE_MODELS[kind]
        if ref_id is None:
            raise ValidationFailed(f"{label} evidence requires ref_id")
        record = session.get(model, ref_id)
        # Tenant check: evidence may only reference objects in the same workspace.
        if record is None or getattr(record, "workspace_id", None) != incident.workspace_id:
            raise NotFound(f"{label} not found in this workspace")
        if not title:
            title = label.capitalize()
    elif kind in (EvidenceKind.EXTERNAL_URL, EvidenceKind.NOTE, EvidenceKind.DEPLOYMENT):
        if not title and not url:
            raise ValidationFailed("evidence requires a title or URL")
    else:  # pragma: no cover - enum guards this
        raise ValidationFailed("unsupported evidence kind")

    report = RedactionReport()
    safe_excerpt = redact_value(excerpt, report)
    safe_metadata = redact_value(metadata or {}, report, "metadata")

    link = EvidenceLink(
        incident_id=incident.id,
        workspace_id=incident.workspace_id,
        kind=kind,
        ref_id=ref_id,
        url=url[:2048],
        title=(title or "")[:240],
        excerpt=safe_excerpt[:10_000],
        metadata_json=safe_metadata,
        added_by_id=actor.id,
        created_at=utcnow(),
    )
    session.add(link)
    session.flush()
    add_timeline(
        session,
        incident,
        event_type=IncidentEventType.EVIDENCE_LINKED,
        actor=actor,
        message=f"Evidence linked: {link.title or kind.value}",
        metadata={"evidence_id": str(link.id), "kind": kind.value},
    )
    record_audit(
        session,
        action="incident.evidence_link",
        workspace_id=incident.workspace_id,
        actor_id=actor.id,
        actor_email=actor.email,
        target_type="incident",
        target_id=incident.id,
        request_id=request_id,
        metadata={"evidence_id": str(link.id), "kind": kind.value},
    )
    return link


def incident_service(session: Session, incident: Incident) -> Service | None:
    return session.get(Service, incident.service_id) if incident.service_id else None


__all__ = [
    "create_incident",
    "transition_incident",
    "assign_owner",
    "add_comment",
    "add_evidence",
    "add_timeline",
    "incident_service",
    "RESOLUTION_REQUIRED_STATUSES",
]
