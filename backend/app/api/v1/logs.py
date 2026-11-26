"""Structured log ingestion (service API key) and bounded log exploration."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, Query, Request, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import WorkspaceContext, enforce_rate_limit, require, utc_from_param
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import PayloadTooLarge, RateLimited, Unauthenticated, ValidationFailed
from app.core.permissions import Permission
from app.core.security import sha256_hex
from app.models.base import utcnow
from app.models.identity import Workspace
from app.models.platform import IdempotencyKey
from app.models.service import Service
from app.models.telemetry import LogEvent
from app.schemas.common import CursorPage
from app.schemas.logs import LogBatchIn, LogEventOut, LogIngestResult

router = APIRouter(tags=["logs"])

IDEMPOTENCY_TTL_HOURS = 24


def get_ingest_service(request: Request, db: Session = Depends(get_db)) -> Service:
    key = request.headers.get("X-Ingestion-Key", "").strip()
    if not key:
        raise Unauthenticated("missing X-Ingestion-Key header")
    service = db.query(Service).filter(Service.ingestion_key_hash == sha256_hex(key)).first()
    if service is None:
        raise Unauthenticated("invalid ingestion key")
    workspace = db.get(Workspace, service.workspace_id)
    if workspace is None:  # pragma: no cover - FK integrity
        raise Unauthenticated("invalid ingestion key")
    enforce_rate_limit(f"ingest:{service.id}", settings.ingest_rate_limit_per_minute, window_seconds=60)
    return service


@router.post("/ingest/logs", response_model=LogIngestResult, status_code=status.HTTP_202_ACCEPTED)
def ingest_logs(
    payload: LogBatchIn,
    service: Service = Depends(get_ingest_service),
    db: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> LogIngestResult:
    serialized = payload.model_dump_json()
    if len(serialized.encode("utf-8")) > settings.max_log_payload_bytes:
        raise PayloadTooLarge(f"log payload exceeds {settings.max_log_payload_bytes} bytes")
    if len(payload.events) > settings.max_log_batch_events:
        raise ValidationFailed(f"batch exceeds {settings.max_log_batch_events} events")

    scope = f"ingest:{service.id}"
    if idempotency_key:
        existing = (
            db.query(IdempotencyKey)
            .filter(IdempotencyKey.scope == scope, IdempotencyKey.key == idempotency_key)
            .first()
        )
        if existing is not None and existing.expires_at > utcnow():
            cached = existing.response_body or {}
            return LogIngestResult(
                accepted=int(cached.get("accepted", 0)),
                duplicates=int(cached.get("duplicates", len(payload.events))),
                redactions=int(cached.get("redactions", 0)),
                event_ids=[uuid.UUID(value) for value in cached.get("event_ids", [])],
            )

    now = utcnow()
    keys = [event.idempotency_key for event in payload.events if event.idempotency_key]
    duplicate_keys: set[str] = set()
    if keys:
        rows = (
            db.query(LogEvent.idempotency_key)
            .filter(
                LogEvent.workspace_id == service.workspace_id,
                LogEvent.idempotency_key.in_(keys),
            )
            .all()
        )
        duplicate_keys = {row[0] for row in rows}

    from app.services.redaction import redact

    accepted = 0
    duplicates = 0
    redactions = 0
    event_ids: list[uuid.UUID] = []

    for event in payload.events:
        if event.idempotency_key and event.idempotency_key in duplicate_keys:
            duplicates += 1
            continue
        message, attributes, report = redact(event.message, event.attributes)
        redactions += report.count
        record = LogEvent(
            workspace_id=service.workspace_id,
            service_id=service.id,
            environment=(event.environment or service.environment.value)[:40],
            severity=event.severity,
            message=message,
            event_timestamp=event.timestamp or now,
            received_at=now,
            attributes=attributes,
            redaction_count=report.count,
            redacted_fields=report.fields,
            trace_id=event.trace_id,
            request_id=event.request_id,
            idempotency_key=event.idempotency_key,
            ingest_source="api",
            payload_bytes=len(json.dumps(event.model_dump(mode="json"), default=str)),
        )
        db.add(record)
        db.flush()
        event_ids.append(record.id)
        accepted += 1

    if idempotency_key:
        db.add(
            IdempotencyKey(
                scope=scope,
                key=idempotency_key[:200],
                request_hash=sha256_hex(serialized),
                response_status=202,
                response_body={
                    "accepted": accepted,
                    "duplicates": duplicates,
                    "redactions": redactions,
                    "event_ids": [str(value) for value in event_ids],
                },
                created_at=now,
                expires_at=now + timedelta(hours=IDEMPOTENCY_TTL_HOURS),
            )
        )
    db.commit()
    return LogIngestResult(
        accepted=accepted,
        duplicates=duplicates,
        redactions=redactions,
        event_ids=event_ids,
    )


@router.get("/workspaces/{workspace_id}/logs", response_model=CursorPage[LogEventOut])
def search_logs(
    from_ts: datetime | None = None,
    to_ts: datetime | None = None,
    service_id: uuid.UUID | None = None,
    environment: str | None = Query(default=None, max_length=40),
    severity: str | None = Query(default=None, max_length=20),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    context: WorkspaceContext = Depends(require(Permission.TELEMETRY_READ_RAW)),
    db: Session = Depends(get_db),
) -> CursorPage[LogEventOut]:
    from app.core.pagination import paginate
    from app.models.telemetry import Severity

    start = utc_from_param(from_ts) or (utcnow() - timedelta(hours=24))
    end = utc_from_param(to_ts) or utcnow()
    if end < start:
        raise ValidationFailed("to_ts must be after from_ts")
    if (end - start).days > settings.max_log_query_range_days:
        raise ValidationFailed(f"log query range is limited to {settings.max_log_query_range_days} days")

    filters = [
        LogEvent.workspace_id == context.workspace_id,
        LogEvent.event_timestamp >= start,
        LogEvent.event_timestamp <= end,
    ]
    if service_id is not None:
        filters.append(LogEvent.service_id == service_id)
    if environment:
        filters.append(LogEvent.environment == environment)
    if severity:
        try:
            filters.append(LogEvent.severity == Severity(severity))
        except ValueError as exc:
            raise ValidationFailed("unknown severity filter") from exc
    if q:
        filters.append(func.lower(LogEvent.message).contains(q.lower().strip()))

    rows, next_cursor = paginate(
        db,
        LogEvent,
        filters=filters,
        order_column=LogEvent.event_timestamp,
        limit=limit,
        cursor=cursor,
    )
    service_names: dict[uuid.UUID, str] = {}
    service_ids = {row.service_id for row in rows if row.service_id}
    if service_ids:
        service_names = {
            service.id: service.name
            for service in db.query(Service).filter(Service.id.in_(service_ids)).all()
        }
    items = []
    for row in rows:
        out = LogEventOut.model_validate(row)
        out.service_name = service_names.get(row.service_id) if row.service_id else None
        items.append(out)
    return CursorPage(items=items, next_cursor=next_cursor, has_more=next_cursor is not None)


__all__ = ["router", "get_ingest_service", "RateLimited"]
