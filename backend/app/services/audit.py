"""Audit event recording. Always called inside the caller's transaction."""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.models.audit import AuditEvent
from app.models.base import utcnow
from app.services.redaction import RedactionReport, redact_value


def record_audit(
    session: Session,
    *,
    action: str,
    workspace_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    actor_email: str = "",
    target_type: str = "",
    target_id: str | uuid.UUID = "",
    outcome: str = "success",
    request_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    safe_metadata = redact_value(metadata or {}, RedactionReport())
    event = AuditEvent(
        workspace_id=workspace_id,
        actor_id=actor_id,
        actor_email=actor_email,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        outcome=outcome,
        request_id=request_id,
        metadata_json=safe_metadata,
        created_at=utcnow(),
    )
    session.add(event)
    return event


__all__ = ["record_audit"]
