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
from datetime import timedelta

from sqlalchemy import delete

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.ai import AIAnalysis
from app.models.audit import AuditEvent
from app.models.base import utcnow
from app.models.identity import Workspace
from app.models.platform import IdempotencyKey, Notification
from app.models.service import HealthCheck, HealthCheckResult, Service
from app.models.telemetry import LogEvent
from app.services.alerts import evaluate_all
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


async def run_health_checks_once(limit: int = 50) -> int:
    executed = 0
    for check_id, service_id in due_health_checks(limit):
        with SessionLocal() as session:
            hc = session.get(HealthCheck, check_id)
            service = session.get(Service, service_id)
            if hc is None or service is None:
                continue
            try:
                await execute_health_check(session, service, hc)
                session.commit()
                executed += 1
            except Exception as exc:  # pragma: no cover - depends on network
                session.rollback()
                logger.warning("health check failed to execute: %s", type(exc).__name__)
    return executed


def evaluate_alerts_once(batch_size: int = 200) -> int:
    with SessionLocal() as session:
        try:
            outcomes = evaluate_all(session, batch_size=batch_size)
            session.commit()
            return len(outcomes)
        except Exception as exc:  # pragma: no cover
            session.rollback()
            logger.warning("alert evaluation failed: %s", type(exc).__name__)
            return 0


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
