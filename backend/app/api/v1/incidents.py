"""Incident lifecycle routes, evidence, comments and AI investigation."""

from __future__ import annotations

import os
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import (
    WorkspaceContext,
    ai_rate_limit,
    require,
    utc_from_param,
)
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.permissions import Permission
from app.models.ai import AIAnalysis
from app.models.alerting import Alert
from app.models.base import utcnow
from app.models.identity import Membership, User
from app.models.incident import (
    EvidenceKind,
    EvidenceLink,
    Incident,
    IncidentEvent,
    IncidentStatus,
)
from app.models.platform import Report
from app.models.service import Service
from app.schemas.ai import AIAnalysisOut, AIFeedbackRequest
from app.schemas.common import CursorPage
from app.schemas.incidents import (
    AIAnalysisBrief,
    EvidenceLinkCreate,
    EvidenceLinkOut,
    IncidentCommentCreate,
    IncidentCreate,
    IncidentDetailOut,
    IncidentEventOut,
    IncidentSummaryOut,
    IncidentUpdate,
    ReportOut,
)
from app.services.ai.orchestrator import record_feedback, run_analysis
from app.services.audit import record_audit
from app.services.incidents import (
    add_comment,
    add_evidence,
    assign_owner,
    create_incident,
    transition_incident,
)
from app.services.reports import render_report

router = APIRouter(prefix="/workspaces/{workspace_id}/incidents", tags=["incidents"])


def _get_incident(db: Session, workspace_id: uuid.UUID, incident_id: uuid.UUID) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None or incident.workspace_id != workspace_id:
        raise NotFound("incident not found")
    return incident


def _summary(db: Session, incident: Incident) -> IncidentSummaryOut:
    service = db.get(Service, incident.service_id) if incident.service_id else None
    owner = db.get(User, incident.owner_id) if incident.owner_id else None
    return IncidentSummaryOut(
        id=incident.id,
        workspace_id=incident.workspace_id,
        title=incident.title,
        status=incident.status,
        severity=incident.severity,
        service_id=incident.service_id,
        service_name=service.name if service else None,
        owner_id=incident.owner_id,
        owner_label=(owner.full_name or owner.email) if owner else None,
        detected_at=incident.detected_at,
        resolved_at=incident.resolved_at,
        closed_at=incident.closed_at,
        created_at=incident.created_at,
        updated_at=incident.updated_at,
    )


def _detail(db: Session, incident: Incident) -> IncidentDetailOut:
    events = (
        db.query(IncidentEvent)
        .filter(IncidentEvent.incident_id == incident.id)
        .order_by(IncidentEvent.created_at.asc())
        .all()
    )
    evidence = (
        db.query(EvidenceLink)
        .filter(EvidenceLink.incident_id == incident.id)
        .order_by(EvidenceLink.created_at.asc())
        .all()
    )
    alerts = db.query(Alert.id).filter(Alert.incident_id == incident.id).all()
    analyses = (
        db.query(AIAnalysis)
        .filter(AIAnalysis.incident_id == incident.id)
        .order_by(AIAnalysis.created_at.desc())
        .limit(5)
        .all()
    )
    base = _summary(db, incident)
    return IncidentDetailOut(
        **base.model_dump(),
        summary=incident.summary,
        resolution_note=incident.resolution_note,
        follow_up_actions=incident.follow_up_actions,
        acknowledged_at=incident.acknowledged_at,
        events=[IncidentEventOut.model_validate(event) for event in events],
        evidence=[EvidenceLinkOut.model_validate(link) for link in evidence],
        alert_ids=[row[0] for row in alerts],
        ai_analyses=[
            AIAnalysisBrief(
                id=analysis.id,
                status=analysis.status.value,
                provider=analysis.provider,
                model_id=analysis.model_id,
                created_at=analysis.created_at,
                feedback=analysis.feedback.value if analysis.feedback else None,
            )
            for analysis in analyses
        ],
    )


def _validate_member(db: Session, workspace_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    if user_id is None:
        return
    membership = (
        db.query(Membership)
        .filter(Membership.workspace_id == workspace_id, Membership.user_id == user_id)
        .first()
    )
    if membership is None:
        raise ValidationFailed("owner must be a member of this workspace")


@router.post("", response_model=IncidentDetailOut, status_code=status.HTTP_201_CREATED)
def open_incident(
    payload: IncidentCreate,
    context: WorkspaceContext = Depends(require(Permission.INCIDENTS_WRITE)),
    db: Session = Depends(get_db),
) -> IncidentDetailOut:
    if payload.service_id is not None:
        service = db.get(Service, payload.service_id)
        if service is None or service.workspace_id != context.workspace_id:
            raise NotFound("service not found")
    _validate_member(db, context.workspace_id, payload.owner_id)
    incident = create_incident(
        db,
        workspace_id=context.workspace_id,
        actor=context.user,
        title=payload.title,
        summary=payload.summary,
        severity=payload.severity,
        service_id=payload.service_id,
        owner_id=payload.owner_id,
        request_id=context.request_id,
    )
    db.commit()
    db.refresh(incident)
    return _detail(db, incident)


@router.get("", response_model=CursorPage[IncidentSummaryOut])
def list_incidents(
    incident_status: IncidentStatus | None = Query(default=None, alias="status"),
    severity: str | None = Query(default=None, max_length=20),
    service_id: uuid.UUID | None = None,
    owner_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=120),
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    context: WorkspaceContext = Depends(require(Permission.INCIDENTS_READ)),
    db: Session = Depends(get_db),
) -> CursorPage[IncidentSummaryOut]:
    from sqlalchemy import func

    from app.core.pagination import paginate

    filters = [Incident.workspace_id == context.workspace_id]
    if incident_status is not None:
        filters.append(Incident.status == incident_status)
    if severity:
        filters.append(Incident.severity == severity)
    if service_id is not None:
        filters.append(Incident.service_id == service_id)
    if owner_id is not None:
        filters.append(Incident.owner_id == owner_id)
    if q:
        filters.append(func.lower(Incident.title).contains(q.lower().strip()))
    if utc_from_param(from_ts):
        filters.append(Incident.detected_at >= utc_from_param(from_ts))
    if utc_from_param(to_ts):
        filters.append(Incident.detected_at <= utc_from_param(to_ts))
    rows, next_cursor = paginate(
        db,
        Incident,
        filters=filters,
        order_column=Incident.created_at,
        limit=limit,
        cursor=cursor,
    )
    return CursorPage(
        items=[_summary(db, row) for row in rows],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.get("/{incident_id}", response_model=IncidentDetailOut)
def get_incident(
    incident_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.INCIDENTS_READ)),
    db: Session = Depends(get_db),
) -> IncidentDetailOut:
    return _detail(db, _get_incident(db, context.workspace_id, incident_id))


@router.patch("/{incident_id}", response_model=IncidentDetailOut)
def update_incident(
    incident_id: uuid.UUID,
    payload: IncidentUpdate,
    context: WorkspaceContext = Depends(require(Permission.INCIDENTS_WRITE)),
    db: Session = Depends(get_db),
) -> IncidentDetailOut:
    incident = _get_incident(db, context.workspace_id, incident_id)
    changes = payload.model_dump(exclude_unset=True)

    if incident.status is IncidentStatus.CLOSED:
        raise Conflict("a closed incident is immutable; reopening is not permitted in the MVP")

    simple_fields = {"title", "summary", "severity"}
    touched = []
    for field in simple_fields:
        if field in changes and changes[field] is not None:
            setattr(incident, field, changes[field])
            touched.append(field)

    if "owner_id" in changes or payload.clear_owner:
        _validate_member(db, context.workspace_id, payload.owner_id)
        owner = db.get(User, payload.owner_id) if payload.owner_id else None
        assign_owner(db, incident, actor=context.user, owner=owner, request_id=context.request_id)

    if payload.follow_up_actions is not None:
        incident.follow_up_actions = [
            action.model_dump() if hasattr(action, "model_dump") else action
            for action in payload.follow_up_actions
        ]
        touched.append("follow_up_actions")

    if touched:
        from app.models.incident import IncidentEventType
        from app.services.incidents import add_timeline

        add_timeline(
            db,
            incident,
            event_type=IncidentEventType.COMMENT,
            actor=context.user,
            message="Updated " + ", ".join(touched),
            metadata={"fields": touched},
        )
        record_audit(
            db,
            action="incident.update",
            workspace_id=context.workspace_id,
            actor_id=context.user.id,
            actor_email=context.user.email,
            target_type="incident",
            target_id=incident.id,
            request_id=context.request_id,
            metadata={"fields": touched},
        )

    if payload.status is not None and payload.status is not incident.status:
        transition_incident(
            db,
            incident,
            actor=context.user,
            new_status=payload.status,
            resolution_note=payload.resolution_note,
            request_id=context.request_id,
        )
    elif payload.resolution_note is not None:
        if incident.status not in (IncidentStatus.RESOLVED, IncidentStatus.CLOSED):
            raise ValidationFailed("resolution notes apply only to resolved or closed incidents")
        incident.resolution_note = payload.resolution_note.strip()

    if payload.comment:
        add_comment(db, incident, actor=context.user, message=payload.comment, request_id=context.request_id)

    db.commit()
    db.refresh(incident)
    return _detail(db, incident)


@router.post("/{incident_id}/comments", response_model=IncidentEventOut, status_code=201)
def comment_on_incident(
    incident_id: uuid.UUID,
    payload: IncidentCommentCreate,
    context: WorkspaceContext = Depends(require(Permission.INCIDENTS_WRITE)),
    db: Session = Depends(get_db),
) -> IncidentEventOut:
    incident = _get_incident(db, context.workspace_id, incident_id)
    event = add_comment(
        db,
        incident,
        actor=context.user,
        message=payload.message,
        request_id=context.request_id,
    )
    db.commit()
    db.refresh(event)
    return IncidentEventOut.model_validate(event)


@router.post("/{incident_id}/evidence", response_model=EvidenceLinkOut, status_code=201)
def link_evidence(
    incident_id: uuid.UUID,
    payload: EvidenceLinkCreate,
    context: WorkspaceContext = Depends(require(Permission.INCIDENTS_WRITE)),
    db: Session = Depends(get_db),
) -> EvidenceLinkOut:
    incident = _get_incident(db, context.workspace_id, incident_id)
    link = add_evidence(
        db,
        incident,
        actor=context.user,
        kind=payload.kind,
        ref_id=payload.ref_id,
        url=payload.url,
        title=payload.title,
        excerpt=payload.excerpt,
        metadata=payload.metadata,
        request_id=context.request_id,
    )
    db.commit()
    db.refresh(link)
    return EvidenceLinkOut.model_validate(link)


@router.get("/{incident_id}/ai-analyses", response_model=list[AIAnalysisOut])
def list_ai_analyses(
    incident_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.INCIDENTS_READ)),
    db: Session = Depends(get_db),
) -> list[AIAnalysisOut]:
    incident = _get_incident(db, context.workspace_id, incident_id)
    rows = (
        db.query(AIAnalysis)
        .filter(AIAnalysis.incident_id == incident.id)
        .order_by(AIAnalysis.created_at.desc())
        .limit(20)
        .all()
    )
    return [AIAnalysisOut.model_validate(row) for row in rows]


@router.post("/{incident_id}/ai-analysis", response_model=AIAnalysisOut)
async def request_ai_analysis(
    incident_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.AI_RUN)),
    db: Session = Depends(get_db),
) -> AIAnalysisOut:
    ai_rate_limit(context)
    incident = _get_incident(db, context.workspace_id, incident_id)
    analysis = await run_analysis(db, incident=incident, actor=context.user, request_id=context.request_id)
    db.commit()
    db.refresh(analysis)
    return AIAnalysisOut.model_validate(analysis)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
def _report_key(workspace_id: uuid.UUID, filename: str) -> tuple[str, str]:
    base = os.path.abspath(settings.reports_dir)
    folder = os.path.join(base, str(workspace_id))
    os.makedirs(folder, exist_ok=True)
    safe_name = os.path.basename(filename)
    path = os.path.join(folder, safe_name)
    if not os.path.abspath(path).startswith(base + os.sep):
        raise ValidationFailed("invalid report path")
    return path, f"{workspace_id}/{safe_name}"


@router.post("/{incident_id}/reports")
def export_report(
    incident_id: uuid.UUID,
    format: str = Query(default="md", pattern="^(md|pdf)$"),
    context: WorkspaceContext = Depends(require(Permission.REPORTS_EXPORT)),
    db: Session = Depends(get_db),
) -> Response:
    incident = _get_incident(db, context.workspace_id, incident_id)
    redaction_level = "viewer" if context.role.value == "viewer" else "standard"
    payload = render_report(db, incident, fmt=format, redaction_level=redaction_level)
    path, object_key = _report_key(context.workspace_id, payload.filename)
    with open(path, "wb") as handle:
        handle.write(payload.content)

    report = Report(
        workspace_id=context.workspace_id,
        incident_id=incident.id,
        fmt=format,
        filename=payload.filename,
        object_key=object_key,
        size_bytes=len(payload.content),
        redaction_level=redaction_level,
        generated_by_id=context.user.id,
        generated_at=utcnow(),
    )
    db.add(report)

    from app.models.incident import IncidentEventType
    from app.services.incidents import add_timeline

    add_timeline(
        db,
        incident,
        event_type=IncidentEventType.REPORT_EXPORTED,
        actor=context.user,
        message=f"Exported {format.upper()} report ({redaction_level} redaction)",
        metadata={"report_id": str(report.id)},
    )
    record_audit(
        db,
        action="report.export",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="incident",
        target_id=incident.id,
        request_id=context.request_id,
        metadata={"format": format, "redaction_level": redaction_level},
    )
    db.commit()
    headers = {"Content-Disposition": f'attachment; filename="{payload.filename}"'}
    return Response(content=payload.content, media_type=payload.media_type, headers=headers)


@router.get("/{incident_id}/reports", response_model=list[ReportOut])
def list_reports(
    incident_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.REPORTS_EXPORT)),
    db: Session = Depends(get_db),
) -> list[ReportOut]:
    incident = _get_incident(db, context.workspace_id, incident_id)
    rows = (
        db.query(Report).filter(Report.incident_id == incident.id).order_by(Report.generated_at.desc()).all()
    )
    return [
        ReportOut(
            id=row.id,
            incident_id=row.incident_id,
            format=row.fmt,
            filename=row.filename,
            size_bytes=row.size_bytes,
            redaction_level=row.redaction_level,
            generated_at=row.generated_at,
        )
        for row in rows
    ]


reports_router = APIRouter(prefix="/workspaces/{workspace_id}/reports", tags=["reports"])


@reports_router.get("/{report_id}/download")
def download_report(
    report_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.REPORTS_EXPORT)),
    db: Session = Depends(get_db),
) -> Response:
    report = db.get(Report, report_id)
    if report is None or report.workspace_id != context.workspace_id:
        raise NotFound("report not found")
    base = os.path.abspath(settings.reports_dir)
    path = os.path.abspath(os.path.join(base, report.object_key))
    if not path.startswith(base + os.sep) or not os.path.isfile(path):
        raise NotFound("report file is no longer available")
    media_type = "application/pdf" if report.fmt == "pdf" else "text/markdown; charset=utf-8"
    with open(path, "rb") as handle:
        content = handle.read()
    headers = {"Content-Disposition": f'attachment; filename="{report.filename}"'}
    return Response(content=content, media_type=media_type, headers=headers)


feedback_router = APIRouter(prefix="/workspaces/{workspace_id}/ai-analyses", tags=["ai"])


@feedback_router.post("/{analysis_id}/feedback", response_model=AIAnalysisOut)
def submit_ai_feedback(
    analysis_id: uuid.UUID,
    payload: AIFeedbackRequest,
    context: WorkspaceContext = Depends(require(Permission.AI_RUN)),
    db: Session = Depends(get_db),
) -> AIAnalysisOut:
    analysis = db.get(AIAnalysis, analysis_id)
    if analysis is None or analysis.workspace_id != context.workspace_id:
        raise NotFound("AI analysis not found")
    record_feedback(
        db,
        analysis,
        actor=context.user,
        feedback=payload.feedback,
        note=payload.note,
        request_id=context.request_id,
    )
    db.commit()
    db.refresh(analysis)
    return AIAnalysisOut.model_validate(analysis)


__all__ = ["router", "reports_router", "feedback_router", "EvidenceKind"]
