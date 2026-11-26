"""Workspace, membership and control-room overview routes."""

from __future__ import annotations

import re
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import WorkspaceContext, get_current_user, require
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import Conflict, NotFound, PermissionDenied, ValidationFailed
from app.core.permissions import Permission, can_manage_role
from app.models.ai import AIAnalysis
from app.models.alerting import Alert
from app.models.base import utcnow
from app.models.identity import Membership, Role, User, Workspace
from app.models.incident import Incident, IncidentStatus
from app.models.integration import WebhookEvent
from app.models.service import Service, ServiceStatus
from app.models.telemetry import LogEvent
from app.schemas.common import Message
from app.schemas.workspace import (
    MemberInvite,
    MemberOut,
    MemberRoleUpdate,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceUpdate,
)
from app.services.audit import record_audit

router = APIRouter(tags=["workspaces"])


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:50]
    return slug or "workspace"


def _unique_slug(db: Session, base: str) -> str:
    slug = base
    suffix = 1
    while db.query(Workspace.id).filter(Workspace.slug == slug).first() is not None:
        suffix += 1
        slug = f"{base[:40]}-{suffix}"
    return slug


def _workspace_out(workspace: Workspace, role: Role | None) -> WorkspaceOut:
    return WorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        slug=workspace.slug,
        timezone=workspace.timezone,
        telemetry_retention_days=workspace.telemetry_retention_days,
        audit_retention_days=workspace.audit_retention_days,
        ai_retention_days=workspace.ai_retention_days,
        ai_data_processing_acknowledged=workspace.ai_data_processing_acknowledged,
        role=role.value if role else None,
        created_at=workspace.created_at,
        updated_at=workspace.updated_at,
    )


@router.post("/workspaces", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
def create_workspace(
    payload: WorkspaceCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceOut:
    workspace = Workspace(
        name=payload.name.strip(),
        slug=_unique_slug(db, _slugify(payload.name)),
        timezone=payload.timezone,
        created_by_id=user.id,
    )
    db.add(workspace)
    db.flush()
    db.add(
        Membership(
            workspace_id=workspace.id,
            user_id=user.id,
            role=Role.OWNER,
            accepted_at=utcnow(),
        )
    )
    record_audit(
        db,
        action="workspace.create",
        workspace_id=workspace.id,
        actor_id=user.id,
        actor_email=user.email,
        target_type="workspace",
        target_id=workspace.id,
        metadata={"name": workspace.name},
    )
    db.commit()
    db.refresh(workspace)
    return _workspace_out(workspace, Role.OWNER)


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[WorkspaceOut]:
    rows = (
        db.query(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .filter(Membership.user_id == user.id)
        .order_by(Workspace.name.asc())
        .all()
    )
    return [_workspace_out(workspace, role) for workspace, role in rows]


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(
    context: WorkspaceContext = Depends(require(Permission.WORKSPACE_READ)),
) -> WorkspaceOut:
    return _workspace_out(context.workspace, context.role)


@router.patch("/workspaces/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(
    payload: WorkspaceUpdate,
    context: WorkspaceContext = Depends(require(Permission.WORKSPACE_UPDATE)),
    db: Session = Depends(get_db),
) -> WorkspaceOut:
    workspace = context.workspace
    changes = payload.model_dump(exclude_unset=True)
    if changes.get("ai_data_processing_acknowledged") and not workspace.ai_data_processing_acknowledged:
        record_audit(
            db,
            action="workspace.ai_notice_acknowledged",
            workspace_id=workspace.id,
            actor_id=context.user.id,
            actor_email=context.user.email,
            target_type="workspace",
            target_id=workspace.id,
        )
    for key, value in changes.items():
        setattr(workspace, key, value)
    record_audit(
        db,
        action="workspace.update",
        workspace_id=workspace.id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="workspace",
        target_id=workspace.id,
        request_id=context.request_id,
        metadata={"fields": sorted(changes)},
    )
    db.commit()
    db.refresh(workspace)
    return _workspace_out(workspace, context.role)


@router.delete("/workspaces/{workspace_id}", response_model=Message)
def delete_workspace(
    confirm: str = Query(..., description="Repeat the workspace slug to confirm deletion"),
    context: WorkspaceContext = Depends(require(Permission.WORKSPACE_DELETE)),
    db: Session = Depends(get_db),
) -> Message:
    if confirm != context.workspace.slug:
        raise ValidationFailed("confirmation slug does not match the workspace slug")
    record_audit(
        db,
        action="workspace.delete",
        workspace_id=context.workspace.id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="workspace",
        target_id=context.workspace.id,
        request_id=context.request_id,
        metadata={"slug": context.workspace.slug},
    )
    db.delete(context.workspace)
    db.commit()
    return Message(message="workspace deleted")


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------
def _member_out(membership: Membership, user: User) -> MemberOut:
    return MemberOut(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=membership.role,
        accepted_at=membership.accepted_at,
        created_at=membership.created_at,
    )


@router.get("/workspaces/{workspace_id}/members", response_model=list[MemberOut])
def list_members(
    context: WorkspaceContext = Depends(require(Permission.MEMBERS_READ)),
    db: Session = Depends(get_db),
) -> list[MemberOut]:
    rows = (
        db.query(Membership, User)
        .join(User, User.id == Membership.user_id)
        .filter(Membership.workspace_id == context.workspace_id)
        .order_by(User.email.asc())
        .all()
    )
    return [_member_out(membership, user) for membership, user in rows]


@router.post(
    "/workspaces/{workspace_id}/members",
    response_model=MemberOut,
    status_code=status.HTTP_201_CREATED,
)
def invite_member(
    payload: MemberInvite,
    context: WorkspaceContext = Depends(require(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_db),
) -> MemberOut:
    if payload.role is Role.OWNER and context.role is not Role.OWNER:
        raise PermissionDenied("only an owner can grant the owner role")
    target = db.query(User).filter(User.email == payload.email.lower().strip()).first()
    if target is None:
        raise NotFound("that person must create an account before they can be added")
    existing = (
        db.query(Membership)
        .filter(
            Membership.workspace_id == context.workspace_id,
            Membership.user_id == target.id,
        )
        .first()
    )
    if existing is not None:
        raise Conflict("user is already a member of this workspace")
    membership = Membership(
        workspace_id=context.workspace_id,
        user_id=target.id,
        role=payload.role,
        invited_by_id=context.user.id,
        accepted_at=utcnow(),
    )
    db.add(membership)
    record_audit(
        db,
        action="member.invite",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="user",
        target_id=target.id,
        request_id=context.request_id,
        metadata={"role": payload.role.value},
    )
    db.commit()
    db.refresh(membership)
    return _member_out(membership, target)


def _owner_count(db: Session, workspace_id: uuid.UUID) -> int:
    return (
        db.query(func.count(Membership.id))
        .filter(Membership.workspace_id == workspace_id, Membership.role == Role.OWNER)
        .scalar()
        or 0
    )


@router.patch("/workspaces/{workspace_id}/members/{user_id}", response_model=MemberOut)
def update_member_role(
    user_id: uuid.UUID,
    payload: MemberRoleUpdate,
    context: WorkspaceContext = Depends(require(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_db),
) -> MemberOut:
    membership = (
        db.query(Membership)
        .filter(
            Membership.workspace_id == context.workspace_id,
            Membership.user_id == user_id,
        )
        .first()
    )
    if membership is None:
        raise NotFound("member not found")
    if not can_manage_role(context.role, membership.role) or not can_manage_role(context.role, payload.role):
        raise PermissionDenied("you cannot manage a member with this role")
    if (
        membership.role is Role.OWNER
        and payload.role is not Role.OWNER
        and _owner_count(db, context.workspace_id) <= 1
    ):
        raise Conflict("a workspace must keep at least one owner")
    membership.role = payload.role
    record_audit(
        db,
        action="member.role_change",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="user",
        target_id=user_id,
        request_id=context.request_id,
        metadata={"role": payload.role.value},
    )
    db.commit()
    target = db.get(User, user_id)
    return _member_out(membership, target)


@router.delete("/workspaces/{workspace_id}/members/{user_id}", response_model=Message)
def remove_member(
    user_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.MEMBERS_MANAGE)),
    db: Session = Depends(get_db),
) -> Message:
    membership = (
        db.query(Membership)
        .filter(
            Membership.workspace_id == context.workspace_id,
            Membership.user_id == user_id,
        )
        .first()
    )
    if membership is None:
        raise NotFound("member not found")
    if not can_manage_role(context.role, membership.role):
        raise PermissionDenied("you cannot remove a member with this role")
    if membership.role is Role.OWNER and _owner_count(db, context.workspace_id) <= 1:
        raise Conflict("a workspace must keep at least one owner")
    record_audit(
        db,
        action="member.remove",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="user",
        target_id=user_id,
        request_id=context.request_id,
    )
    db.delete(membership)
    db.commit()
    return Message(message="member removed")


# ---------------------------------------------------------------------------
# Overview (control room landing data)
# ---------------------------------------------------------------------------
@router.get("/workspaces/{workspace_id}/overview")
def overview(
    context: WorkspaceContext = Depends(require(Permission.WORKSPACE_READ)),
    db: Session = Depends(get_db),
) -> dict:
    since_24h = utcnow() - timedelta(hours=24)
    active_incidents = (
        db.query(Incident)
        .filter(
            Incident.workspace_id == context.workspace_id,
            Incident.status.notin_([IncidentStatus.RESOLVED, IncidentStatus.CLOSED]),
        )
        .order_by(Incident.detected_at.desc())
        .limit(10)
        .all()
    )
    status_rows = (
        db.query(Service.status, func.count(Service.id))
        .filter(Service.workspace_id == context.workspace_id)
        .group_by(Service.status)
        .all()
    )
    service_counts = {status_.value: 0 for status_ in ServiceStatus}
    for status_, count in status_rows:
        service_counts[status_.value] = count

    recent_alerts = (
        db.query(Alert)
        .filter(Alert.workspace_id == context.workspace_id)
        .order_by(Alert.created_at.desc())
        .limit(8)
        .all()
    )
    recent_deployments = (
        db.query(WebhookEvent)
        .filter(WebhookEvent.workspace_id == context.workspace_id)
        .order_by(WebhookEvent.received_at.desc())
        .limit(8)
        .all()
    )
    logs_24h = (
        db.query(func.count(LogEvent.id))
        .filter(
            LogEvent.workspace_id == context.workspace_id,
            LogEvent.received_at >= since_24h,
        )
        .scalar()
        or 0
    )
    last_log_at = (
        db.query(func.max(LogEvent.received_at))
        .filter(LogEvent.workspace_id == context.workspace_id)
        .scalar()
    )
    ai_counts = {
        (key.value if hasattr(key, "value") else str(key)): count
        for key, count in db.query(AIAnalysis.status, func.count(AIAnalysis.id))
        .filter(AIAnalysis.workspace_id == context.workspace_id)
        .group_by(AIAnalysis.status)
        .all()
    }
    feedback_counts = {
        (key.value if hasattr(key, "value") else str(key)): count
        for key, count in db.query(AIAnalysis.feedback, func.count(AIAnalysis.id))
        .filter(
            AIAnalysis.workspace_id == context.workspace_id,
            AIAnalysis.feedback.isnot(None),
        )
        .group_by(AIAnalysis.feedback)
        .all()
    }

    def _dt(value):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else None

    return {
        "workspace": {
            "id": str(context.workspace.id),
            "name": context.workspace.name,
            "timezone": context.workspace.timezone,
            "role": context.role.value,
        },
        "services": service_counts,
        "active_incidents": [
            {
                "id": str(incident.id),
                "title": incident.title,
                "status": incident.status.value,
                "severity": incident.severity.value,
                "detected_at": _dt(incident.detected_at),
            }
            for incident in active_incidents
        ],
        "recent_alerts": [
            {
                "id": str(alert.id),
                "title": alert.title,
                "status": alert.status.value,
                "severity": alert.severity.value,
                "occurrence_count": alert.occurrence_count,
                "created_at": _dt(alert.created_at),
            }
            for alert in recent_alerts
        ],
        "recent_deployments": [
            {
                "id": str(event.id),
                "event_type": event.event_type,
                "action": event.action,
                "repository": event.repository_full_name,
                "ref": event.deployment_ref,
                "commit_shas": event.commit_shas,
                "occurred_at": _dt(event.occurred_at),
            }
            for event in recent_deployments
        ],
        "ingestion": {
            "events_24h": logs_24h,
            "last_received_at": _dt(last_log_at),
            "healthy": bool(last_log_at and last_log_at >= utcnow() - timedelta(hours=1)),
        },
        "ai": {
            "completed": ai_counts.get("completed", 0),
            "failed": ai_counts.get("failed", 0),
            "feedback": feedback_counts,
            "provider": settings.ai_provider,
        },
    }


@router.get("/workspaces/{workspace_id}/notifications")
def list_notifications(
    context: WorkspaceContext = Depends(require(Permission.ALERTS_READ)),
    db: Session = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    from app.models.platform import Notification

    rows = (
        db.query(Notification)
        .filter(
            Notification.workspace_id == context.workspace_id,
            Notification.user_id == context.user.id,
        )
        .order_by(Notification.created_at.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(row.id),
            "channel": row.channel,
            "subject": row.subject,
            "body": row.body,
            "related_type": row.related_type,
            "related_id": row.related_id,
            "status": row.status.value,
            "created_at": row.created_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        for row in rows
    ]


__all__ = ["router"]
