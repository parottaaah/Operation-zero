"""Health-check execution and service-state machine."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.base import utcnow
from app.models.service import (
    HealthCheck,
    HealthCheckResult,
    HealthResultStatus,
    Service,
    ServiceStatus,
)
from app.services.ssrf import safe_fetch

logger = logging.getLogger(__name__)


def _effective_status(service: Service, hc: HealthCheck, result: HealthResultStatus) -> ServiceStatus:
    if not hc.enabled:
        return ServiceStatus.PAUSED
    passed = result is HealthResultStatus.PASS
    if passed:
        if hc.consecutive_successes >= hc.recovery_threshold:
            return ServiceStatus.HEALTHY
        if service.status is ServiceStatus.DOWN:
            return ServiceStatus.DEGRADED
        return service.status if service.status is not ServiceStatus.UNKNOWN else ServiceStatus.HEALTHY
    if hc.consecutive_failures >= hc.failure_threshold:
        return ServiceStatus.DOWN
    if service.status is ServiceStatus.DOWN:
        return ServiceStatus.DOWN
    return ServiceStatus.DEGRADED


async def execute_health_check(session: Session, service: Service, hc: HealthCheck) -> HealthCheckResult:
    outcome = await safe_fetch(
        hc.url,
        method=hc.method,
        timeout_seconds=hc.timeout_seconds,
    )
    now = utcnow()

    if outcome.error_kind == "timeout":
        result_status = HealthResultStatus.TIMEOUT
    elif outcome.error_kind:
        result_status = HealthResultStatus.ERROR
    elif outcome.status_code in set(hc.expected_status_codes or [200]):
        result_status = HealthResultStatus.PASS
    else:
        result_status = HealthResultStatus.FAIL

    if result_status is HealthResultStatus.PASS:
        hc.consecutive_successes += 1
        hc.consecutive_failures = 0
        hc.last_error = ""
    else:
        hc.consecutive_failures += 1
        hc.consecutive_successes = 0
        hc.last_error = (outcome.error_message or f"HTTP {outcome.status_code}")[:500]

    new_status = _effective_status(service, hc, result_status)
    service.status = new_status
    service.last_checked_at = now

    result = HealthCheckResult(
        workspace_id=service.workspace_id,
        service_id=service.id,
        health_check_id=hc.id,
        checked_at=now,
        status=result_status,
        status_code=outcome.status_code,
        latency_ms=round(outcome.latency_ms, 2),
        error_kind=outcome.error_kind,
        error_message=hc.last_error,
        effective_status=new_status,
    )
    session.add(result)
    session.flush()
    logger.info(
        "health check",
        extra={
            "service_id": str(service.id),
            "status": result_status.value,
            "service_status": new_status.value,
            "latency_ms": result.latency_ms,
        },
    )
    return result


def check_is_due(hc: HealthCheck, now=None) -> bool:
    now = now or utcnow()
    if not hc.enabled:
        return False
    service = hc.service
    if service is None:
        return False
    if service.status is ServiceStatus.PAUSED:
        return False
    if service.last_checked_at is None:
        return True
    return service.last_checked_at <= now - timedelta(seconds=hc.interval_seconds)


__all__ = ["execute_health_check", "check_is_due"]
