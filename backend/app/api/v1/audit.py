"""Audit log query routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import WorkspaceContext, require, utc_from_param
from app.core.db import get_db
from app.core.pagination import paginate
from app.core.permissions import Permission
from app.models.audit import AuditEvent
from app.schemas.common import CursorPage
from app.schemas.workspace import AuditEventOut

router = APIRouter(prefix="/workspaces/{workspace_id}/audit-events", tags=["audit"])


@router.get("", response_model=CursorPage[AuditEventOut])
def list_audit_events(
    action: str | None = Query(default=None, max_length=80),
    actor_email: str | None = Query(default=None, max_length=320),
    target_type: str | None = Query(default=None, max_length=60),
    from_ts: str | None = Query(default=None, max_length=40),
    to_ts: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    context: WorkspaceContext = Depends(require(Permission.AUDIT_READ)),
    db: Session = Depends(get_db),
) -> CursorPage[AuditEventOut]:
    from datetime import datetime

    filters = [AuditEvent.workspace_id == context.workspace_id]
    if action:
        filters.append(AuditEvent.action == action)
    if actor_email:
        filters.append(func.lower(AuditEvent.actor_email) == actor_email.lower().strip())
    if target_type:
        filters.append(AuditEvent.target_type == target_type)

    def _parse(value: str | None):
        if not value:
            return None
        try:
            return utc_from_param(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            from app.core.errors import ValidationFailed

            raise ValidationFailed("timestamps must be ISO-8601") from None

    start = _parse(from_ts)
    end = _parse(to_ts)
    if start:
        filters.append(AuditEvent.created_at >= start)
    if end:
        filters.append(AuditEvent.created_at <= end)

    rows, next_cursor = paginate(
        db,
        AuditEvent,
        filters=filters,
        order_column=AuditEvent.created_at,
        limit=limit,
        cursor=cursor,
    )
    return CursorPage(
        items=[AuditEventOut.model_validate(row) for row in rows],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.get("/actions", response_model=list[str])
def list_audit_actions(
    context: WorkspaceContext = Depends(require(Permission.AUDIT_READ)),
    db: Session = Depends(get_db),
) -> list[str]:
    rows = (
        db.query(AuditEvent.action)
        .filter(AuditEvent.workspace_id == context.workspace_id)
        .distinct()
        .order_by(AuditEvent.action.asc())
        .all()
    )
    return [row[0] for row in rows]


__all__ = ["router"]
