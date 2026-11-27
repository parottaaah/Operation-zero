"""Background worker: health checks, alert evaluation and retention cleanup.

Runs as its own process/container (``python -m app.workers.runner``) and can also be
embedded in the API process for single-process development deployments.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import signal
import time
import uuid
from datetime import timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.ai import AIAnalysis
from app.models.alerting import AlertRule
from app.models.audit import AuditEvent
from app.models.base import utcnow
from app.models.identity import Workspace
from app.models.platform import IdempotencyKey, Notification, WorkerDeadLetter
from app.models.service import HealthCheck, HealthCheckResult, Service
from app.models.telemetry import LogEvent
from app.services.alerts import evaluate_rule
from app.services.healthcheck import check_is_due, execute_health_check

logger = logging.getLogger(__name__)


def due_health_checks(limit: int = 100) -> list[tuple]:
    with SessionLocal() as session:
        rows = (
            session.query(HealthCheck, Service)
            .join(Service, Service.id == HealthCheck.service_id)
            .filter(HealthCheck.enabled.is_(True), Service.status != "paused")
            .limit(limit * 4)
            .all()
        )
        due = [(hc.id, service.id) for hc, service in rows if check_is_due(hc, now=utcnow())][:limit]
        return due


def _retry_delay(attempt: int) -> float:
    """Bounded exponential delay before the next attempt."""
    return min(
        settings.worker_retry_base_seconds * (2 ** (attempt - 1)),
        settings.worker_retry_max_seconds,
    )


def _record_dead_letter(*, workspace_id, job_type: str, job_id, attempts: int, error: str) -> None:
    """Persist an exhausted job. Operators inspect ``worker_dead_letters``."""
    with SessionLocal() as session:
        row = (
            session.query(WorkerDeadLetter)
            .filter(
                WorkerDeadLetter.job_type == job_type,
                WorkerDeadLetter.job_id == str(job_id),
            )
            .first()
        )
        now = utcnow()
        if row is None:
            row = WorkerDeadLetter(
                workspace_id=workspace_id,
                job_type=job_type,
                job_id=str(job_id),
                attempts=attempts,
                last_error=error[:1000],
                created_at=now,
                updated_at=now,
            )
            session.add(row)
        else:
            row.attempts = attempts
            row.last_error = error[:1000]
            row.updated_at = now
        session.commit()


def _clear_dead_letter(session: Session, job_type: str, job_id) -> None:
    session.query(WorkerDeadLetter).filter(
        WorkerDeadLetter.job_type == job_type,
        WorkerDeadLetter.job_id == str(job_id),
    ).delete(synchronize_session=False)


async def _run_health_check_job(check_id, service_id) -> bool:
    attempts = max(1, settings.worker_max_attempts)
    last_error = ""
    workspace_id = None
    for attempt in range(1, attempts + 1):
        with SessionLocal() as session:
            health_check = session.get(HealthCheck, check_id)
            service = session.get(Service, service_id)
            if health_check is None or service is None:
                return False
            workspace_id = service.workspace_id
            try:
                await execute_health_check(session, service, health_check)
                _clear_dead_letter(session, "health_check", check_id)
                session.commit()
                return True
            except Exception as exc:  # pragma: no cover - depends on network
                session.rollback()
                last_error = f"{type(exc).__name__}: {exc}"[:1000]
                logger.warning(
                    "health check %s attempt %s/%s failed: %s",
                    check_id,
                    attempt,
                    attempts,
                    type(exc).__name__,
                )
        if attempt < attempts:
            delay = _retry_delay(attempt)
            if delay > 0:
                await asyncio.sleep(delay)
    if workspace_id is not None:
        _record_dead_letter(
            workspace_id=workspace_id,
            job_type="health_check",
            job_id=check_id,
            attempts=attempts,
            error=last_error,
        )
    return False


async def run_health_checks_once(limit: int = 50) -> int:
    executed = 0
    for check_id, service_id in due_health_checks(limit):
        if await _run_health_check_job(check_id, service_id):
            executed += 1
    return executed


def _due_alert_rules(batch_size: int) -> list[tuple[uuid.UUID, uuid.UUID]]:
    with SessionLocal() as session:
        rows = (
            session.query(AlertRule.id, AlertRule.workspace_id)
            .filter(AlertRule.enabled.is_(True))
            .order_by(AlertRule.last_evaluated_at.asc().nullsfirst())
            .limit(batch_size)
            .all()
        )
        return [(row[0], row[1]) for row in rows]


def _run_alert_rule_job(rule_id, workspace_id) -> bool:
    attempts = max(1, settings.worker_max_attempts)
    last_error = ""
    for attempt in range(1, attempts + 1):
        with SessionLocal() as session:
            rule = session.get(AlertRule, rule_id)
            if rule is None:
                return False
            try:
                evaluate_rule(session, rule)
                _clear_dead_letter(session, "alert_rule", rule_id)
                session.commit()
                return True
            except Exception as exc:  # pragma: no cover - depends on DB state
                session.rollback()
                last_error = f"{type(exc).__name__}: {exc}"[:1000]
                logger.warning(
                    "alert rule %s attempt %s/%s failed: %s",
                    rule_id,
                    attempt,
                    attempts,
                    type(exc).__name__,
                )
        if attempt < attempts:
            delay = _retry_delay(attempt)
            if delay > 0:
                time.sleep(delay)
    _record_dead_letter(
        workspace_id=workspace_id,
        job_type="alert_rule",
        job_id=rule_id,
        attempts=attempts,
        error=last_error,
    )
    return False


def evaluate_alerts_once(batch_size: int = 200) -> int:
    evaluated = 0
    for rule_id, workspace_id in _due_alert_rules(batch_size):
        if _run_alert_rule_job(rule_id, workspace_id):
            evaluated += 1
    return evaluated


def cleanup_retention_once() -> dict[str, int]:
    """Delete data past each workspace's retention policy."""
    now = utcnow()
    deleted = {"logs": 0, "health_results": 0, "audit": 0, "ai": 0, "idempotency": 0}
    with SessionLocal() as session:
        workspaces = session.query(Workspace).all()
        for workspace in workspaces:
            log_cutoff = now - timedelta(days=workspace.telemetry_retention_days)
            deleted["logs"] += (
                session.execute(
                    delete(LogEvent).where(
                        LogEvent.workspace_id == workspace.id,
                        LogEvent.event_timestamp < log_cutoff,
                    )
                ).rowcount
                or 0
            )
            deleted["health_results"] += (
                session.execute(
                    delete(HealthCheckResult).where(
                        HealthCheckResult.workspace_id == workspace.id,
                        HealthCheckResult.checked_at < log_cutoff,
                    )
                ).rowcount
                or 0
            )
            ai_cutoff = now - timedelta(days=workspace.ai_retention_days)
            deleted["ai"] += (
                session.execute(
                    delete(AIAnalysis).where(
                        AIAnalysis.workspace_id == workspace.id,
                        AIAnalysis.created_at < ai_cutoff,
                    )
                ).rowcount
                or 0
            )
            audit_cutoff = now - timedelta(days=workspace.audit_retention_days)
            deleted["audit"] += (
                session.execute(
                    delete(AuditEvent).where(
                        AuditEvent.workspace_id == workspace.id,
                        AuditEvent.created_at < audit_cutoff,
                    )
                ).rowcount
                or 0
            )
        deleted["idempotency"] = (
            session.execute(delete(IdempotencyKey).where(IdempotencyKey.expires_at < now)).rowcount or 0
        )
        session.execute(delete(Notification).where(Notification.created_at < now - timedelta(days=90)))
        session.commit()
    return deleted


async def run_once() -> dict:
    checks = await run_health_checks_once(settings.worker_batch_size)
    rules = evaluate_alerts_once(settings.worker_batch_size)
    return {"health_checks": checks, "alert_rules_evaluated": rules}


async def run_forever() -> None:
    logger.info("OPERATION ZERO worker starting")
    last_check = 0.0
    last_eval = 0.0
    last_cleanup = 0.0
    stop = asyncio.Event()

    def _stop(*_args):
        stop.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with contextlib.suppress(NotImplementedError):  # pragma: no cover - windows
            loop.add_signal_handler(sig, _stop)

    backoff = 1
    while not stop.is_set():
        try:
            now = time.monotonic()
            if now - last_check >= settings.healthcheck_interval_seconds:
                executed = await run_health_checks_once(settings.worker_batch_size)
                last_check = now
                if executed:
                    logger.info("executed %s health checks", executed)
            if now - last_eval >= settings.alert_eval_interval_seconds:
                evaluated = evaluate_alerts_once(settings.worker_batch_size)
                last_eval = now
                if evaluated:
                    logger.info("evaluated %s alert rules", evaluated)
            if now - last_cleanup >= 3600:
                logger.info("retention cleanup: %s", cleanup_retention_once())
                last_cleanup = now
            backoff = 1
        except Exception as exc:  # pragma: no cover - defensive loop
            logger.exception("worker cycle failed: %s", type(exc).__name__)
            backoff = min(backoff * 2, settings.worker_max_backoff_seconds)
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=backoff)
    logger.info("OPERATION ZERO worker stopped")


__all__ = [
    "run_forever",
    "run_once",
    "run_health_checks_once",
    "evaluate_alerts_once",
    "cleanup_retention_once",
    "due_health_checks",
]
