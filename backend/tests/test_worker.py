"""Worker behaviour: due checks, alert evaluation wiring and retention cleanup."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta

from app.models import (
    AuditEvent,
    HealthCheck,
    IdempotencyKey,
    Service,
    Workspace,
    utcnow,
)
from app.models.telemetry import LogEvent
from app.workers import runner


def _seed_service(session_factory, status="unknown", last_checked_at=None):
    from app.models import User

    with session_factory() as session:
        user = User(email=f"w{uuid.uuid4().hex[:6]}@example.com", full_name="W", password_hash="h")
        session.add(user)
        session.flush()
        workspace = Workspace(name="Worker WS", slug=f"w{uuid.uuid4().hex[:8]}", created_by_id=user.id)
        session.add(workspace)
        session.flush()
        service = Service(
            workspace_id=workspace.id,
            name="worker-service",
            slug="worker-service",
            status=status,
            last_checked_at=last_checked_at,
            ingestion_key_hash="h" * 64,
        )
        session.add(service)
        session.flush()
        health_check = HealthCheck(
            workspace_id=workspace.id,
            service_id=service.id,
            url="https://example.com/health",
        )
        session.add(health_check)
        session.commit()
        return workspace.id, service.id, health_check.id


def test_due_health_checks_finds_unchecked_services(session_factory, monkeypatch):
    monkeypatch.setattr(runner, "SessionLocal", session_factory)
    _, service_id, _ = _seed_service(session_factory)
    due = runner.due_health_checks()
    assert service_id in [service for _, service in due]


def test_paused_services_are_skipped(session_factory, monkeypatch):
    monkeypatch.setattr(runner, "SessionLocal", session_factory)
    _seed_service(session_factory, status="paused")
    assert runner.due_health_checks() == []


def test_run_health_checks_once_executes_and_commits(session_factory, monkeypatch):
    monkeypatch.setattr(runner, "SessionLocal", session_factory)
    workspace_id, service_id, hc_id = _seed_service(session_factory)
    executed = []

    async def fake_execute(session, service, health_check):
        executed.append((service.id, health_check.id))
        service.last_checked_at = utcnow()
        session.commit()

    monkeypatch.setattr(runner, "execute_health_check", fake_execute)
    count = asyncio.run(runner.run_health_checks_once())
    assert count == 1
    assert executed[0][0] == service_id
    assert executed[0][1] == hc_id


def test_evaluate_alerts_once_delegates(session_factory, monkeypatch):
    monkeypatch.setattr(runner, "SessionLocal", session_factory)
    monkeypatch.setattr(runner, "evaluate_all", lambda session, batch_size=200: [object(), object()])
    assert runner.evaluate_alerts_once() == 2


def test_retention_cleanup_respects_workspace_policy(session_factory, monkeypatch):
    monkeypatch.setattr(runner, "SessionLocal", session_factory)
    workspace_id, service_id, _ = _seed_service(session_factory)
    old = utcnow() - timedelta(days=90)
    recent = utcnow() - timedelta(days=1)

    with session_factory() as session:
        workspace = session.get(Workspace, workspace_id)
        workspace.telemetry_retention_days = 30
        workspace.audit_retention_days = 30
        session.commit()

    with session_factory() as session:
        for ts, message in [(old, "old log"), (recent, "recent log")]:
            session.add(
                LogEvent(
                    workspace_id=workspace_id,
                    service_id=service_id,
                    environment="production",
                    severity="info",
                    message=message,
                    event_timestamp=ts,
                    received_at=ts,
                    attributes={},
                    payload_bytes=10,
                )
            )
        session.add(
            AuditEvent(
                workspace_id=workspace_id,
                actor_email="a@b.c",
                action="old.action",
                target_type="x",
                target_id="1",
                outcome="success",
                request_id="",
                metadata_json={},
                created_at=old,
            )
        )
        session.add(
            IdempotencyKey(
                scope="s",
                key="expired",
                created_at=old,
                expires_at=old,
                response_body={},
            )
        )
        session.commit()

    result = runner.cleanup_retention_once()
    assert result["logs"] == 1
    assert result["audit"] == 1
    assert result["idempotency"] == 1

    with session_factory() as session:
        remaining = session.query(LogEvent.message).all()
        assert remaining == [("recent log",)]
        assert session.query(AuditEvent).count() == 0
        assert session.query(IdempotencyKey).count() == 0


def test_worker_once_returns_summary(session_factory, monkeypatch):
    monkeypatch.setattr(runner, "SessionLocal", session_factory)

    async def no_checks(limit=50):
        return 0

    monkeypatch.setattr(runner, "run_health_checks_once", no_checks)
    monkeypatch.setattr(runner, "evaluate_alerts_once", lambda batch_size=200: 0)
    summary = asyncio.run(runner.run_once())
    assert summary == {"health_checks": 0, "alert_rules_evaluated": 0}
