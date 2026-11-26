"""Service registry, health-check configuration and health history."""

from __future__ import annotations

import re
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import WorkspaceContext, require
from app.core.db import get_db
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.permissions import Permission
from app.core.security import new_api_key
from app.models.base import utcnow
from app.models.incident import Incident
from app.models.service import (
    Environment,
    HealthCheck,
    HealthCheckResult,
    HealthResultStatus,
    Service,
    ServiceStatus,
)
from app.schemas.common import CursorPage, Message
from app.schemas.service import (
    HealthCheckConfigIn,
    HealthCheckOut,
    HealthResultOut,
    IngestionKeyOut,
    RunCheckOut,
    ServiceCreate,
    ServiceCreatedOut,
    ServiceHealthSummary,
    ServiceOut,
    ServiceUpdate,
)
from app.services import ssrf
from app.services.audit import record_audit
from app.services.healthcheck import execute_health_check

router = APIRouter(prefix="/workspaces/{workspace_id}/services", tags=["services"])


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:60] or "service"


def _service_out(service: Service) -> ServiceOut:
    return ServiceOut.model_validate(service)


def _get_service(db: Session, workspace_id: uuid.UUID, service_id: uuid.UUID) -> Service:
    service = db.get(Service, service_id)
    if service is None or service.workspace_id != workspace_id:
        raise NotFound("service not found")
    return service


def _validate_health_url(payload: HealthCheckConfigIn) -> None:
    try:
        ssrf.validate_url(payload.url)
    except ssrf.SsrfBlocked as exc:  # pragma: no cover - exercised via API tests
        from app.core.errors import SsrfBlocked

        raise SsrfBlocked(str(exc)) from exc


@router.post("", response_model=ServiceCreatedOut, status_code=status.HTTP_201_CREATED)
def create_service(
    payload: ServiceCreate,
    context: WorkspaceContext = Depends(require(Permission.SERVICES_WRITE)),
    db: Session = Depends(get_db),
) -> ServiceCreatedOut:
    name = payload.name.strip()
    duplicate = (
        db.query(Service.id)
        .filter(
            Service.workspace_id == context.workspace_id,
            func.lower(Service.name) == name.lower(),
            Service.environment == payload.environment,
        )
        .first()
    )
    if duplicate is not None:
        raise Conflict("a service with this name already exists in this environment")
    if payload.health_check is not None:
        _validate_health_url(payload.health_check)

    raw_key, key_hash, last4 = new_api_key()
    service = Service(
        workspace_id=context.workspace_id,
        name=name,
        slug=_slugify(name),
        environment=payload.environment,
        description=payload.description,
        owner_team=payload.owner_team,
        status=ServiceStatus.UNKNOWN,
        ingestion_key_hash=key_hash,
        ingestion_key_last4=last4,
        created_by_id=context.user.id,
    )
    db.add(service)
    db.flush()
    if payload.health_check is not None:
        hc = payload.health_check
        db.add(
            HealthCheck(
                workspace_id=context.workspace_id,
                service_id=service.id,
                url=hc.url,
                method=hc.method,
                expected_status_codes=hc.expected_status_codes,
                interval_seconds=hc.interval_seconds,
                timeout_seconds=hc.timeout_seconds,
                failure_threshold=hc.failure_threshold,
                recovery_threshold=hc.recovery_threshold,
                enabled=hc.enabled,
            )
        )
    record_audit(
        db,
        action="service.create",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="service",
        target_id=service.id,
        request_id=context.request_id,
        metadata={"name": name, "environment": payload.environment.value},
    )
    db.commit()
    db.refresh(service)
    return ServiceCreatedOut(
        **_service_out(service).model_dump(),
        ingestion_key=raw_key,
    )


@router.get("", response_model=CursorPage[ServiceOut])
def list_services(
    environment: Environment | None = None,
    service_status: ServiceStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    context: WorkspaceContext = Depends(require(Permission.SERVICES_READ)),
    db: Session = Depends(get_db),
) -> CursorPage[ServiceOut]:
    from app.core.pagination import paginate

    filters = [Service.workspace_id == context.workspace_id]
    if environment is not None:
        filters.append(Service.environment == environment)
    if service_status is not None:
        filters.append(Service.status == service_status)
    if q:
        filters.append(func.lower(Service.name).contains(q.lower().strip()))
    rows, next_cursor = paginate(
        db,
        Service,
        filters=filters,
        order_column=Service.created_at,
        limit=limit,
        cursor=cursor,
    )
    return CursorPage(
        items=[_service_out(row) for row in rows],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.get("/{service_id}", response_model=ServiceOut)
def get_service(
    service_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.SERVICES_READ)),
    db: Session = Depends(get_db),
) -> ServiceOut:
    return _service_out(_get_service(db, context.workspace_id, service_id))


@router.patch("/{service_id}", response_model=ServiceOut)
def update_service(
    service_id: uuid.UUID,
    payload: ServiceUpdate,
    context: WorkspaceContext = Depends(require(Permission.SERVICES_WRITE)),
    db: Session = Depends(get_db),
) -> ServiceOut:
    service = _get_service(db, context.workspace_id, service_id)
    changes = payload.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in (
        ServiceStatus.PAUSED,
        ServiceStatus.UNKNOWN,
    ):
        raise ValidationFailed("only the paused or unknown status may be set manually")
    if "name" in changes:
        new_name = changes["name"].strip()
        duplicate = (
            db.query(Service.id)
            .filter(
                Service.workspace_id == context.workspace_id,
                Service.id != service.id,
                func.lower(Service.name) == new_name.lower(),
                Service.environment == service.environment,
            )
            .first()
        )
        if duplicate is not None:
            raise Conflict("another service already uses this name in this environment")
        service.slug = _slugify(new_name)
        changes["name"] = new_name
    for key, value in changes.items():
        setattr(service, key, value)
    record_audit(
        db,
        action="service.update",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="service",
        target_id=service.id,
        request_id=context.request_id,
        metadata={"fields": sorted(changes)},
    )
    db.commit()
    db.refresh(service)
    return _service_out(service)


@router.delete("/{service_id}", response_model=Message)
def delete_service(
    service_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.SERVICES_WRITE)),
    db: Session = Depends(get_db),
) -> Message:
    service = _get_service(db, context.workspace_id, service_id)
    active = (
        db.query(Incident.id)
        .filter(
            Incident.workspace_id == context.workspace_id,
            Incident.service_id == service.id,
            Incident.status.notin_(["resolved", "closed"]),
        )
        .first()
    )
    if active is not None:
        raise Conflict("resolve or close active incidents before deleting this service")
    record_audit(
        db,
        action="service.delete",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="service",
        target_id=service.id,
        request_id=context.request_id,
        metadata={"name": service.name},
    )
    db.delete(service)
    db.commit()
    return Message(message="service deleted")


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------
@router.put("/{service_id}/health-check", response_model=HealthCheckOut)
def configure_health_check(
    service_id: uuid.UUID,
    payload: HealthCheckConfigIn,
    context: WorkspaceContext = Depends(require(Permission.SERVICES_WRITE)),
    db: Session = Depends(get_db),
) -> HealthCheckOut:
    service = _get_service(db, context.workspace_id, service_id)
    _validate_health_url(payload)
    hc = service.health_check
    if hc is None:
        hc = HealthCheck(
            workspace_id=context.workspace_id,
            service_id=service.id,
            url=payload.url,
        )
        db.add(hc)
        service.health_check = hc
    hc.url = payload.url
    hc.method = payload.method
    hc.expected_status_codes = payload.expected_status_codes
    hc.interval_seconds = payload.interval_seconds
    hc.timeout_seconds = payload.timeout_seconds
    hc.failure_threshold = payload.failure_threshold
    hc.recovery_threshold = payload.recovery_threshold
    hc.enabled = payload.enabled
    if not payload.enabled:
        service.status = ServiceStatus.PAUSED
    elif service.status is ServiceStatus.PAUSED:
        service.status = ServiceStatus.UNKNOWN
    record_audit(
        db,
        action="service.health_check_configure",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="service",
        target_id=service.id,
        request_id=context.request_id,
        metadata={
            "url_host": ssrf.urlparse(payload.url).hostname,
            "interval_seconds": payload.interval_seconds,
            "timeout_seconds": payload.timeout_seconds,
            "enabled": payload.enabled,
        },
    )
    db.commit()
    db.refresh(hc)
    return HealthCheckOut.model_validate(hc)


@router.delete("/{service_id}/health-check", response_model=Message)
def delete_health_check(
    service_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.SERVICES_WRITE)),
    db: Session = Depends(get_db),
) -> Message:
    service = _get_service(db, context.workspace_id, service_id)
    if service.health_check is None:
        raise NotFound("this service has no health check configured")
    db.delete(service.health_check)
    service.status = ServiceStatus.UNKNOWN
    record_audit(
        db,
        action="service.health_check_delete",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="service",
        target_id=service.id,
        request_id=context.request_id,
    )
    db.commit()
    return Message(message="health check removed")


@router.post("/{service_id}/health-check/run", response_model=RunCheckOut)
async def run_health_check_now(
    service_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.SERVICES_WRITE)),
    db: Session = Depends(get_db),
) -> RunCheckOut:
    service = _get_service(db, context.workspace_id, service_id)
    if service.health_check is None:
        raise NotFound("this service has no health check configured")
    result = await execute_health_check(db, service, service.health_check)
    record_audit(
        db,
        action="service.health_check_run",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="service",
        target_id=service.id,
        request_id=context.request_id,
        metadata={"result": result.status.value},
    )
    db.commit()
    db.refresh(result)
    return RunCheckOut(
        result=HealthResultOut.model_validate(result),
        service_status=service.status,
    )


@router.get("/{service_id}/health", response_model=ServiceHealthSummary)
def service_health_history(
    service_id: uuid.UUID,
    hours: int = Query(default=24, ge=1, le=168),
    limit: int = Query(default=100, ge=1, le=500),
    context: WorkspaceContext = Depends(require(Permission.SERVICES_READ)),
    db: Session = Depends(get_db),
) -> ServiceHealthSummary:
    service = _get_service(db, context.workspace_id, service_id)
    since = utcnow() - timedelta(hours=hours)
    query = db.query(HealthCheckResult).filter(
        HealthCheckResult.workspace_id == context.workspace_id,
        HealthCheckResult.service_id == service.id,
        HealthCheckResult.checked_at >= since,
    )
    total = query.count()
    passed = query.filter(HealthCheckResult.status == HealthResultStatus.PASS).count()
    latencies = [float(row[0]) for row in query.with_entities(HealthCheckResult.latency_ms).all() if row[0]]
    latencies.sort()
    p95 = None
    if latencies:
        import math

        p95 = latencies[max(0, math.ceil(0.95 * len(latencies)) - 1)]
    results = query.order_by(HealthCheckResult.checked_at.desc()).limit(limit).all()
    return ServiceHealthSummary(
        service=_service_out(service),
        results=[HealthResultOut.model_validate(row) for row in results],
        availability=(passed / total) if total else None,
        p95_latency_ms=p95,
    )


@router.post("/{service_id}/ingestion-key/rotate", response_model=IngestionKeyOut)
def rotate_ingestion_key(
    service_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.SERVICES_WRITE)),
    db: Session = Depends(get_db),
) -> IngestionKeyOut:
    service = _get_service(db, context.workspace_id, service_id)
    raw_key, key_hash, last4 = new_api_key()
    service.ingestion_key_hash = key_hash
    service.ingestion_key_last4 = last4
    service.ingestion_key_rotated_at = utcnow()
    record_audit(
        db,
        action="service.ingestion_key_rotate",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="service",
        target_id=service.id,
        request_id=context.request_id,
    )
    db.commit()
    return IngestionKeyOut(service_id=service.id, ingestion_key=raw_key, ingestion_key_last4=last4)


__all__ = ["router"]
