"""Seed a synthetic demo workspace so the control room is explorable offline.

Everything written here is generated data: no customer telemetry, no real
credentials. The seed is deterministic apart from the clock, so screenshots and
bug reports stay comparable between runs.

Usage (after ``alembic upgrade head``)::

    python -m app.scripts.seed_demo            # create if absent
    python -m app.scripts.seed_demo --force    # wipe the demo workspace, reseed

The seed is idempotent: running it twice leaves exactly one demo workspace.
It refuses to run when ``OZ_ENV`` is production or staging.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.core.security import hash_password, new_api_key
from app.models import Base
from app.models.ai import AIAnalysis, AIAnalysisStatus
from app.models.alerting import (
    Alert,
    AlertMetric,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    Comparator,
)
from app.models.audit import AuditEvent
from app.models.base import utcnow
from app.models.identity import Membership, Role, User, Workspace
from app.models.incident import (
    EvidenceKind,
    EvidenceLink,
    Incident,
    IncidentEvent,
    IncidentEventType,
    IncidentStatus,
)
from app.models.integration import WebhookEvent, WebhookStatus
from app.models.platform import Notification, NotificationStatus
from app.models.service import (
    Environment,
    HealthCheck,
    HealthCheckResult,
    HealthResultStatus,
    Service,
    ServiceStatus,
)
from app.models.telemetry import LogEvent, Severity
from app.services.redaction import redact

DEMO_WORKSPACE_SLUG = "demo-engineering"
DEMO_WORKSPACE_NAME = "Demo Engineering"
DEMO_PASSWORD = "DemoZero-2026!"
#: A routable-looking but synthetic domain: ".local" is rejected by EmailStr.
DEMO_EMAIL_DOMAIN = "demo.operation-zero.dev"

#: Demo accounts. One password for all of them keeps the demo easy to explain;
#: the password is printed at the end of the run and is never stored in clear.
DEMO_USERS: tuple[tuple[str, str, Role], ...] = (
    ("owner", "Aarav Owner", Role.OWNER),
    ("engineer", "Meera Engineer", Role.ENGINEER),
    ("analyst", "Kani Analyst", Role.SECURITY_ANALYST),
    ("viewer", "Vikram Viewer", Role.VIEWER),
)

HEALTH_SAMPLE_COUNT = 24
HEALTH_SAMPLE_INTERVAL = timedelta(minutes=5)
LOG_BATCH = 40


@dataclass
class ServiceSeed:
    service: Service
    health_check: HealthCheck
    ingestion_key: str
    results: list[HealthCheckResult] = field(default_factory=list)


@dataclass
class SeedSummary:
    created: bool
    workspace_id: uuid.UUID
    workspace_name: str
    accounts: list[tuple[str, str]] = field(default_factory=list)
    service_keys: list[tuple[str, str]] = field(default_factory=list)
    services: int = 0
    log_events: int = 0
    alerts: int = 0
    incidents: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _user_email(handle: str) -> str:
    return f"{handle}@{DEMO_EMAIL_DOMAIN}"


def _get_or_create_user(session: Session, email: str, full_name: str) -> User:
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(
            email=email,
            full_name=full_name,
            password_hash=hash_password(DEMO_PASSWORD),
            is_active=True,
        )
        session.add(user)
        session.flush()
    return user


def _reset_demo_workspace(session: Session, workspace: Workspace) -> None:
    """Delete every demo row except the workspace itself.

    The workspace row is kept so the workspace id stays stable across reseeds
    (a browser holding the old id keeps working). Children are removed
    child-first using the metadata dependency order, so the reset works with
    and without database-level ``ON DELETE CASCADE``.
    """
    for table in reversed(Base.metadata.sorted_tables):
        if "workspace_id" in table.c:
            session.execute(table.delete().where(table.c.workspace_id == workspace.id))
    session.flush()

    for handle, _name, _role in DEMO_USERS:
        user = session.execute(select(User).where(User.email == _user_email(handle))).scalar_one_or_none()
        if user is not None:
            has_membership = session.execute(
                select(Membership.id).where(Membership.user_id == user.id)
            ).first()
            if has_membership is None:
                session.delete(user)
    session.flush()


def _ensure_database_ready() -> None:
    """Fail early with an actionable message instead of a half-seeded database."""
    if settings.database_url.startswith("sqlite"):
        prefix = "sqlite:///"
        path = Path(settings.database_url[len(prefix) :])
        if path.parent and str(path.parent) not in {"", "."}:
            path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with engine.connect() as connection:
            connection.execute(select(1))
    except OperationalError as exc:  # pragma: no cover - operator guidance path
        raise SystemExit(f"cannot reach the database: {exc.orig}") from exc


def _require_schema() -> None:
    from sqlalchemy import inspect

    existing = set(inspect(engine).get_table_names())
    missing = sorted({table.name for table in Base.metadata.sorted_tables} - existing)
    if missing:
        raise SystemExit(
            "database schema is incomplete (missing: "
            + ", ".join(missing[:5])
            + ("...)" if len(missing) > 5 else ")")
            + ")\nRun `make migrate` (alembic upgrade head) first."
        )


# ---------------------------------------------------------------------------
# Seed sections
# ---------------------------------------------------------------------------
def _seed_identity(session: Session, workspace: Workspace | None = None) -> tuple[Workspace, dict[str, User]]:
    users: dict[str, User] = {}
    for handle, full_name, _role in DEMO_USERS:
        users[handle] = _get_or_create_user(session, _user_email(handle), full_name)

    owner = users["owner"]
    if workspace is None:
        workspace = Workspace()
        session.add(workspace)
    workspace.name = DEMO_WORKSPACE_NAME
    workspace.slug = DEMO_WORKSPACE_SLUG
    workspace.timezone = "Asia/Kolkata"
    workspace.telemetry_retention_days = settings.telemetry_default_retention_days
    workspace.audit_retention_days = settings.audit_default_retention_days
    workspace.ai_retention_days = settings.ai_default_retention_days
    workspace.ai_data_processing_acknowledged = False
    workspace.created_by_id = owner.id
    session.flush()

    now = utcnow()
    for handle, _full_name, role in DEMO_USERS:
        session.add(
            Membership(
                workspace_id=workspace.id,
                user_id=users[handle].id,
                role=role,
                invited_by_id=owner.id if handle != "owner" else None,
                accepted_at=now,
            )
        )
    session.flush()
    return workspace, users


def _seed_services(
    session: Session, workspace: Workspace, owner: User
) -> tuple[dict[str, ServiceSeed], list[ServiceSeed]]:
    specs = [
        {
            "name": "checkout-api",
            "environment": Environment.PRODUCTION,
            "owner_team": "Payments",
            "description": "Customer checkout orchestration; calls the payments authorizer.",
            "status": ServiceStatus.DEGRADED,
            "health_url": "https://checkout.example.com/healthz",
        },
        {
            "name": "payments-api",
            "environment": Environment.PRODUCTION,
            "owner_team": "Payments",
            "description": "Card authorisation and capture gateway wrapper.",
            "status": ServiceStatus.HEALTHY,
            "health_url": "https://payments.example.com/healthz",
        },
        {
            "name": "webhook-worker",
            "environment": Environment.PRODUCTION,
            "owner_team": "Platform",
            "description": "Delivers outbound merchant webhooks with retries and backoff.",
            "status": ServiceStatus.HEALTHY,
            "health_url": "https://webhooks.example.com/healthz",
        },
        {
            "name": "search-api",
            "environment": Environment.STAGING,
            "owner_team": "Search",
            "description": "Product search and faceting; staging cut-over this week.",
            "status": ServiceStatus.DOWN,
            "health_url": "https://search.staging.example.com/healthz",
        },
    ]

    seeded: list[ServiceSeed] = []
    for spec in specs:
        raw_key, key_hash, last4 = new_api_key()
        service = Service(
            workspace_id=workspace.id,
            name=spec["name"],
            slug=spec["name"],
            environment=spec["environment"],
            description=spec["description"],
            status=spec["status"],
            owner_team=spec["owner_team"],
            last_checked_at=utcnow() - timedelta(minutes=2),
            created_by_id=owner.id,
            ingestion_key_hash=key_hash,
            ingestion_key_last4=last4,
        )
        session.add(service)
        session.flush()

        # Enabled checks would make the demo non-deterministic (they need a live
        # endpoint and egress). The seeded history below is the demo signal;
        # enable the check in the UI once it points at a reachable URL.
        health_check = HealthCheck(
            workspace_id=workspace.id,
            service_id=service.id,
            url=spec["health_url"],
            method="GET",
            expected_status_codes=[200],
            interval_seconds=60,
            timeout_seconds=5,
            failure_threshold=2,
            recovery_threshold=1,
            enabled=False,
            consecutive_failures=2 if spec["status"] is ServiceStatus.DEGRADED else 0,
            consecutive_successes=0,
            last_error="upstream timeout after 5000ms" if spec["status"] is ServiceStatus.DEGRADED else "",
        )
        session.add(health_check)
        session.flush()

        seeded.append(ServiceSeed(service, health_check, raw_key))

    _seed_health_history(session, workspace, seeded)
    return {item.service.name: item for item in seeded}, seeded


def _seed_health_history(session: Session, workspace: Workspace, seeded: list[ServiceSeed]) -> None:
    now = utcnow().replace(second=0, microsecond=0)
    plans: dict[str, list[HealthResultStatus]] = {
        "checkout-api": [HealthResultStatus.PASS] * 18 + [HealthResultStatus.FAIL] * 6,
        "payments-api": [HealthResultStatus.PASS] * HEALTH_SAMPLE_COUNT,
        "webhook-worker": [HealthResultStatus.PASS] * (HEALTH_SAMPLE_COUNT - 1) + [HealthResultStatus.ERROR],
        "search-api": [HealthResultStatus.PASS] * 20 + [HealthResultStatus.TIMEOUT] * 4,
    }

    for item in seeded:
        statuses = plans[item.service.name]
        for index, status in enumerate(statuses):
            checked_at = now - HEALTH_SAMPLE_INTERVAL * (len(statuses) - 1 - index)
            failing = status is not HealthResultStatus.PASS
            latency = 2400.0 + index * 37.5 if failing else 90.0 + index * 4.5
            result = HealthCheckResult(
                workspace_id=workspace.id,
                service_id=item.service.id,
                health_check_id=item.health_check.id,
                checked_at=checked_at,
                status=status,
                status_code=None if status is HealthResultStatus.TIMEOUT else (200 if not failing else 503),
                latency_ms=round(latency, 1),
                error_kind="" if not failing else status.value,
                error_message=""
                if not failing
                else "request exceeded 5000ms timeout"
                if status is HealthResultStatus.TIMEOUT
                else "upstream returned 503",
                effective_status=item.service.status,
            )
            session.add(result)
            item.results.append(result)
    session.flush()


def _seed_logs(
    session: Session, workspace: Workspace, services: dict[str, ServiceSeed]
) -> dict[str, LogEvent]:
    """Insert redacted log events and return the ones referenced as evidence."""
    now = utcnow().replace(microsecond=0)
    plan: list[tuple[str, Severity, int, str, dict]] = [
        (
            "checkout-api",
            Severity.CRITICAL,
            61,
            "payment authorizer timed out after 3000ms while creating order 8842",
            {"http.status_code": 504, "upstream": "payments-authorizer", "route": "/checkout"},
        ),
        (
            "checkout-api",
            Severity.ERROR,
            58,
            "checkout failed: upstream timeout (retry 1/2)",
            {"http.status_code": 504, "retry": 1, "route": "/checkout"},
        ),
        (
            "checkout-api",
            Severity.ERROR,
            44,
            "connection pool exhausted: waiting for available connection",
            {"db.pool.size": 20, "db.pool.checked_out": 20},
        ),
        (
            "checkout-api",
            Severity.WARNING,
            39,
            "database connection string rotated; using postgresql://app:SuperSecret@db:5432/checkout",
            {"component": "db", "rotation": "scheduled"},
        ),
        (
            "checkout-api",
            Severity.ERROR,
            24,
            "checkout failed: upstream timeout (retry 2/2)",
            {"http.status_code": 504, "retry": 2, "route": "/checkout"},
        ),
        (
            "payments-api",
            Severity.INFO,
            63,
            "authorisation approved in 187ms",
            {"amount_minor": 4999},
        ),
        (
            "payments-api",
            Severity.INFO,
            41,
            "capture settled for order 8839",
            {"amount_minor": 4999},
        ),
        (
            "payments-api",
            Severity.WARNING,
            33,
            "provider latency above SLO: 812ms",
            {"provider": "cardnet"},
        ),
        (
            "webhook-worker",
            Severity.WARNING,
            70,
            "webhook delivery retry scheduled (attempt 4/6)",
            {"merchant": "m_204"},
        ),
        (
            "webhook-worker",
            Severity.ERROR,
            51,
            "webhook delivery failed after 6 attempts",
            {"merchant": "m_204", "event": "payment.succeeded"},
        ),
        (
            "webhook-worker",
            Severity.INFO,
            12,
            "webhook backlog drained to 0",
            {"queue_depth": 0},
        ),
        (
            "search-api",
            Severity.ERROR,
            96,
            "upstream search cluster unavailable: 503",
            {"cluster": "search-staging-2"},
        ),
        (
            "search-api",
            Severity.INFO,
            6,
            "staging pod restarted after failing readiness probe",
            {"pod": "search-api-7d9f"},
        ),
    ]

    refs: dict[str, LogEvent] = {}
    for index, (service_name, severity, minutes_ago, message, attributes) in enumerate(plan):
        item = services[service_name]
        event_at = now - timedelta(minutes=minutes_ago)
        safe_message, safe_attributes, report = redact(message, attributes)
        event = LogEvent(
            workspace_id=workspace.id,
            service_id=item.service.id,
            environment=item.service.environment.value,
            severity=severity,
            message=safe_message,
            event_timestamp=event_at,
            received_at=event_at + timedelta(seconds=1),
            attributes=safe_attributes,
            redaction_count=report.count,
            redacted_fields=list(dict.fromkeys(report.fields)),
            trace_id=f"tr_{index:04d}{uuid.uuid4().hex[:8]}",
            request_id=f"req_{uuid.uuid4().hex[:12]}",
            idempotency_key=f"seed-{index:04d}",
            ingest_source="seed",
            payload_bytes=len(message.encode("utf-8")),
        )
        session.add(event)
        session.flush()
        if service_name == "checkout-api" and severity in {Severity.ERROR, Severity.CRITICAL}:
            refs[f"checkout-{len(refs)}"] = event
    return refs


def _seed_deployments(
    session: Session, workspace: Workspace, services: dict[str, ServiceSeed]
) -> WebhookEvent:
    """Record the delivery context around the incident (no GitHub app required)."""
    now = utcnow().replace(microsecond=0)
    checkout = services["checkout-api"].service

    deployment = WebhookEvent(
        workspace_id=workspace.id,
        integration_id=None,
        provider="github",
        delivery_id="seed-delivery-0001",
        event_type="deployment_status",
        action="created",
        status=WebhookStatus.VERIFIED,
        signature_verified=True,
        repository_full_name="example-org/checkout-api",
        commit_shas=["9f2c1ab7d3"],
        deployment_ref="deploy-4821",
        actor_login="meera.engineer",
        occurred_at=now - timedelta(minutes=70),
        received_at=now - timedelta(minutes=70),
        payload={
            "state": "success",
            "environment": checkout.environment.value,
            "ref": "main",
            "note": "Synthetic demo delivery",
        },
    )
    pull_request = WebhookEvent(
        workspace_id=workspace.id,
        integration_id=None,
        provider="github",
        delivery_id="seed-delivery-0002",
        event_type="pull_request",
        action="opened",
        status=WebhookStatus.VERIFIED,
        signature_verified=True,
        repository_full_name="example-org/checkout-api",
        commit_shas=["c41ab90e57"],
        pr_number=482,
        actor_login="payments.bot",
        occurred_at=now - timedelta(minutes=25),
        received_at=now - timedelta(minutes=25),
        payload={
            "title": "Raise authorizer timeout and add retry budget",
            "note": "Synthetic demo delivery",
        },
    )
    session.add_all([deployment, pull_request])
    session.flush()
    return deployment


def _seed_alerting(
    session: Session, workspace: Workspace, services: dict[str, ServiceSeed], owner: User
) -> tuple[AlertRule, list[Alert]]:
    now = utcnow().replace(microsecond=0)
    checkout = services["checkout-api"].service
    webhooks = services["webhook-worker"].service

    availability = AlertRule(
        workspace_id=workspace.id,
        service_id=checkout.id,
        name="Checkout availability below 95%",
        metric=AlertMetric.AVAILABILITY,
        comparator=Comparator.LT,
        threshold=0.95,
        window_seconds=600,
        dedup_window_seconds=1800,
        severity=AlertSeverity.CRITICAL,
        description="Fires when the success rate of checkout health checks drops under 95%.",
        enabled=True,
        notify_channels=["in_app", "email"],
        created_by_id=owner.id,
        last_evaluated_at=now - timedelta(minutes=2),
    )
    latency = AlertRule(
        workspace_id=workspace.id,
        service_id=checkout.id,
        name="Checkout p95 latency above 800ms",
        metric=AlertMetric.LATENCY_P95,
        comparator=Comparator.GT,
        threshold=800.0,
        window_seconds=600,
        dedup_window_seconds=900,
        severity=AlertSeverity.WARNING,
        description="Fires when p95 checkout latency stays above the 800ms objective.",
        enabled=True,
        notify_channels=["in_app"],
        created_by_id=owner.id,
        last_evaluated_at=now - timedelta(minutes=2),
    )
    error_rate = AlertRule(
        workspace_id=workspace.id,
        service_id=webhooks.id,
        name="Webhook error rate above 2%",
        metric=AlertMetric.ERROR_RATE,
        comparator=Comparator.GT,
        threshold=0.02,
        window_seconds=900,
        dedup_window_seconds=1800,
        severity=AlertSeverity.WARNING,
        description="Fires when webhook delivery errors exceed 2% of attempts.",
        enabled=True,
        notify_channels=["in_app"],
        created_by_id=owner.id,
        last_evaluated_at=now - timedelta(minutes=3),
    )
    session.add_all([availability, latency, error_rate])
    session.flush()

    firing = Alert(
        workspace_id=workspace.id,
        rule_id=availability.id,
        service_id=checkout.id,
        status=AlertStatus.FIRING,
        severity=AlertSeverity.CRITICAL,
        title="Checkout availability below 95%",
        description="Availability measured at 75% over the last 10 minutes.",
        trigger_value=0.75,
        threshold=0.95,
        window_seconds=600,
        dedup_key=f"{availability.id}:{checkout.id}",
        occurrence_count=6,
        first_seen_at=now - timedelta(minutes=32),
        last_seen_at=now - timedelta(minutes=2),
        notified_at=now - timedelta(minutes=31),
        notified_channels=["in_app"],
    )
    slow = Alert(
        workspace_id=workspace.id,
        rule_id=latency.id,
        service_id=checkout.id,
        status=AlertStatus.ACKNOWLEDGED,
        severity=AlertSeverity.WARNING,
        title="Checkout p95 latency above 800ms",
        description="p95 latency measured at 2412ms over the last 10 minutes.",
        trigger_value=2412.0,
        threshold=800.0,
        window_seconds=600,
        dedup_key=f"{latency.id}:{checkout.id}",
        occurrence_count=3,
        first_seen_at=now - timedelta(minutes=48),
        last_seen_at=now - timedelta(minutes=6),
        acknowledged_at=now - timedelta(minutes=40),
        notified_at=now - timedelta(minutes=47),
        notified_channels=["in_app"],
    )
    session.add_all([firing, slow])
    session.flush()

    session.add(
        Notification(
            workspace_id=workspace.id,
            user_id=owner.id,
            channel="in_app",
            subject="Checkout availability below 95%",
            body="checkout-api availability is 75% over the last 10 minutes.",
            related_type="alert",
            related_id=str(firing.id),
            status=NotificationStatus.SENT,
            created_at=now - timedelta(minutes=31),
            sent_at=now - timedelta(minutes=31),
        )
    )
    session.flush()
    return availability, [firing, slow]


def _seed_incidents(
    session: Session,
    workspace: Workspace,
    services: dict[str, ServiceSeed],
    users: dict[str, User],
    alerts: list[Alert],
    log_refs: dict[str, LogEvent],
    deployment: WebhookEvent,
) -> list[Incident]:
    now = utcnow().replace(microsecond=0)
    owner = users["owner"]
    engineer = users["engineer"]
    analyst = users["analyst"]
    checkout = services["checkout-api"]
    webhooks = services["webhook-worker"].service
    search = services["search-api"].service

    detected = now - timedelta(minutes=61)
    incident = Incident(
        workspace_id=workspace.id,
        title="Checkout latency spike on production",
        summary=(
            "Checkout p95 latency rose to 2.4s and requests began failing with upstream "
            "timeouts against the payment authorizer. Merchants report failed purchases."
        ),
        status=IncidentStatus.INVESTIGATING,
        severity=AlertSeverity.CRITICAL,
        service_id=checkout.service.id,
        owner_id=engineer.id,
        created_by_id=owner.id,
        detected_at=detected,
        acknowledged_at=detected + timedelta(minutes=6),
        follow_up_actions=[
            {
                "text": "Add a circuit breaker around the authorizer client",
                "owner": "Payments",
                "done": False,
            },
            {
                "text": "Raise the checkout DB pool ceiling and alert on saturation",
                "owner": "Platform",
                "done": True,
            },
        ],
    )
    retries = Incident(
        workspace_id=workspace.id,
        title="Webhook delivery retries climbing",
        summary=(
            "Merchant webhook delivery attempts 4-6 are exhausting the retry budget for "
            "payment.succeeded events. Backlog peaked at 1.2k messages."
        ),
        status=IncidentStatus.MONITORING,
        severity=AlertSeverity.WARNING,
        service_id=webhooks.id,
        owner_id=owner.id,
        created_by_id=analyst.id,
        detected_at=now - timedelta(hours=4),
        acknowledged_at=now - timedelta(hours=3, minutes=50),
        follow_up_actions=[
            {"text": "Add merchant-level retry budget telemetry", "owner": "Platform", "done": False},
        ],
    )
    search_outage = Incident(
        workspace_id=workspace.id,
        title="Search API returned 503 for six minutes",
        summary="Staging search cluster lost readiness after a node replacement.",
        status=IncidentStatus.RESOLVED,
        severity=AlertSeverity.INFO,
        service_id=search.id,
        owner_id=engineer.id,
        created_by_id=engineer.id,
        detected_at=now - timedelta(minutes=96),
        acknowledged_at=now - timedelta(minutes=94),
        resolved_at=now - timedelta(minutes=84),
        resolution_note="Node replacement completed; readiness probes passing for 10 minutes.",
        follow_up_actions=[
            {"text": "Pin the staging cluster to 3 nodes during rollout", "owner": "Search", "done": True},
        ],
    )
    session.add_all([incident, retries, search_outage])
    session.flush()

    for alert in alerts:
        alert.incident_id = incident.id

    events = [
        (
            incident,
            IncidentEventType.CREATED,
            owner,
            "Incident opened from the alert 'Checkout availability below 95%'.",
            "",
            IncidentStatus.OPEN.value,
            detected,
        ),
        (
            incident,
            IncidentEventType.ASSIGNMENT,
            owner,
            f"Assigned to {engineer.full_name}.",
            IncidentStatus.OPEN.value,
            IncidentStatus.OPEN.value,
            detected + timedelta(minutes=2),
        ),
        (
            incident,
            IncidentEventType.STATUS_CHANGE,
            engineer,
            "Acknowledged and started investigating.",
            IncidentStatus.OPEN.value,
            IncidentStatus.ACKNOWLEDGED.value,
            detected + timedelta(minutes=6),
        ),
        (
            incident,
            IncidentEventType.STATUS_CHANGE,
            engineer,
            "Root-cause hypotheses being validated against logs and health checks.",
            IncidentStatus.ACKNOWLEDGED.value,
            IncidentStatus.INVESTIGATING.value,
            detected + timedelta(minutes=9),
        ),
        (
            incident,
            IncidentEventType.COMMENT,
            engineer,
            "p95 checkout latency is 2.4s. Authorizer timeouts start at the same minute "
            "the DB pool hit 100% saturation.",
            IncidentStatus.INVESTIGATING.value,
            IncidentStatus.INVESTIGATING.value,
            detected + timedelta(minutes=22),
        ),
        (
            incident,
            IncidentEventType.EVIDENCE_LINKED,
            analyst,
            "Linked 3 error logs, 2 failed health checks and the authorizer PR.",
            IncidentStatus.INVESTIGATING.value,
            IncidentStatus.INVESTIGATING.value,
            detected + timedelta(minutes=28),
        ),
        (
            retries,
            IncidentEventType.CREATED,
            analyst,
            "Opened after the retry-budget alert fired twice in 15 minutes.",
            "",
            IncidentStatus.OPEN.value,
            now - timedelta(hours=4),
        ),
        (
            retries,
            IncidentEventType.STATUS_CHANGE,
            owner,
            "Mitigation deployed; watching queue depth before resolving.",
            IncidentStatus.INVESTIGATING.value,
            IncidentStatus.MONITORING.value,
            now - timedelta(minutes=40),
        ),
        (
            search_outage,
            IncidentEventType.CREATED,
            engineer,
            "Readiness probe failures in staging search.",
            "",
            IncidentStatus.OPEN.value,
            now - timedelta(minutes=96),
        ),
        (
            search_outage,
            IncidentEventType.STATUS_CHANGE,
            engineer,
            "Recovered after node replacement.",
            IncidentStatus.MONITORING.value,
            IncidentStatus.RESOLVED.value,
            now - timedelta(minutes=84),
        ),
    ]
    for inc, event_type, actor, message, from_status, to_status, created_at in events:
        session.add(
            IncidentEvent(
                incident_id=inc.id,
                workspace_id=workspace.id,
                event_type=event_type,
                actor_id=actor.id if actor else None,
                actor_label=actor.full_name or actor.email if actor else "system",
                message=message,
                from_status=from_status,
                to_status=to_status,
                metadata_json={},
                created_at=created_at,
            )
        )

    failed_results = [r for r in checkout.results if r.status is not HealthResultStatus.PASS][-2:]
    evidence: list[tuple[EvidenceKind, uuid.UUID | None, str, str, dict]] = [
        (
            EvidenceKind.LOG_EVENT,
            log_refs["checkout-0"].id,
            "/logs?severity=critical&service=checkout-api",
            "Critical checkout log",
            "Checkout authorizer timed out after 3000ms while creating order 8842.",
            {"severity": "critical", "service": "checkout-api"},
        ),
        (
            EvidenceKind.LOG_EVENT,
            log_refs["checkout-1"].id,
            "/logs?severity=error&service=checkout-api",
            "Error log",
            "Connection pool exhausted: waiting for an available connection.",
            {"severity": "error", "service": "checkout-api"},
        ),
        (
            EvidenceKind.LOG_EVENT,
            log_refs["checkout-2"].id,
            "/logs?severity=error&service=checkout-api",
            "Error log",
            "Checkout failed: upstream timeout on retry 2/2.",
            {"severity": "error", "service": "checkout-api"},
        ),
        (
            EvidenceKind.HEALTH_CHECK_RESULT,
            failed_results[-1].id,
            f"/services/{checkout.service.id}",
            "Failed health check",
            "Health check failed at " + failed_results[-1].checked_at.strftime("%H:%M UTC") + ".",
            {"status": failed_results[-1].status.value},
        ),
        (
            EvidenceKind.HEALTH_CHECK_RESULT,
            failed_results[0].id,
            f"/services/{checkout.service.id}",
            "Failed health check",
            "Health check failed at " + failed_results[0].checked_at.strftime("%H:%M UTC") + ".",
            {"status": failed_results[0].status.value},
        ),
        (
            EvidenceKind.EXTERNAL_URL,
            None,
            "https://github.com/example-org/checkout-api/pull/482",
            "PR #482: raise authorizer timeout and add retry budget",
            "Draft PR opened by the payments team at 11:42 UTC.",
            {"repository": "example-org/checkout-api", "pr_number": 482},
        ),
        (
            EvidenceKind.DEPLOYMENT,
            deployment.id,
            "https://github.com/example-org/checkout-api/actions",
            "Deploy deploy-4821 (success)",
            "Deployment to production succeeded 9 minutes before the first timeout.",
            {"deployment_ref": deployment.deployment_ref, "commit": deployment.commit_shas},
        ),
        (
            EvidenceKind.NOTE,
            None,
            "",
            "Handover note",
            "Authorizer vendor confirmed no outage; latency is on our side of the hop.",
            {},
        ),
    ]
    for index, (kind, ref_id, url, title, excerpt, metadata) in enumerate(evidence):
        session.add(
            EvidenceLink(
                incident_id=incident.id,
                workspace_id=workspace.id,
                kind=kind,
                ref_id=ref_id,
                url=url,
                title=title[:240],
                excerpt=excerpt,
                metadata_json=metadata,
                added_by_id=analyst.id,
                created_at=detected + timedelta(minutes=28 + index),
            )
        )

    analysis = AIAnalysis(
        workspace_id=workspace.id,
        incident_id=incident.id,
        requested_by_id=engineer.id,
        status=AIAnalysisStatus.COMPLETED,
        provider="local-deterministic",
        model_id="rules-v1",
        prompt_version=settings.ai_prompt_version,
        evidence_ids=["E1", "E2", "E3", "E4", "E5"],
        output={
            "observed_facts": [
                {
                    "text": "Checkout health checks failed 6 times in the last 30 minutes.",
                    "citations": ["E4", "E5"],
                },
                {
                    "text": "Payment authorizer calls exceeded the 3s timeout on order 8842.",
                    "citations": ["E1"],
                },
                {
                    "text": "The database connection pool reported 20/20 connections in use.",
                    "citations": ["E2"],
                },
            ],
            "hypotheses": [
                {
                    "text": "Connection-pool saturation amplifies authorizer latency.",
                    "reasoning": "Pool exhaustion and authorizer timeouts start in the same minute.",
                    "confidence": "medium",
                    "citations": ["E2", "E3"],
                }
            ],
            "missing_information": [
                "Authorizer-side latency percentiles for the same window are not ingested."
            ],
            "recommended_next_checks": [
                "Compare authorizer client timeout configuration in the deployed commit.",
                "Confirm whether pool size changed in the last deployment.",
            ],
            "sources": {
                "E1": {
                    "kind": "log",
                    "ref_id": str(log_refs["checkout-0"].id),
                    "label": "authorizer timeout",
                },
                "E2": {"kind": "log", "ref_id": str(log_refs["checkout-1"].id), "label": "pool exhausted"},
                "E3": {"kind": "log", "ref_id": str(log_refs["checkout-2"].id), "label": "retry 2/2"},
                "E4": {"kind": "health_check_result", "ref_id": str(failed_results[0].id), "label": "failed"},
                "E5": {
                    "kind": "health_check_result",
                    "ref_id": str(failed_results[-1].id),
                    "label": "failed",
                },
            },
            "meta": {
                "provider": "local-deterministic",
                "model_id": "rules-v1",
                "prompt_version": settings.ai_prompt_version,
                "evidence_count": 5,
                "instruction_markers_in_evidence": 0,
                "disclaimer": (
                    "Observed facts cite stored evidence. Hypotheses are unvalidated and must be "
                    "checked by a human before any action."
                ),
            },
        },
        citation_count=5,
        invalid_citations=[],
        latency_ms=12.4,
        created_at=detected + timedelta(minutes=35),
    )
    session.add(analysis)

    now_audit = [
        ("service.create", owner, "service", checkout.service.id),
        ("incident.create", owner, "incident", incident.id),
        ("incident.status_change", engineer, "incident", incident.id),
        ("incident.evidence_link", analyst, "incident", incident.id),
        ("ai.analysis_request", engineer, "ai_analysis", analysis.id),
    ]
    for offset, (action, actor, target_type, target_id) in enumerate(now_audit):
        session.add(
            AuditEvent(
                workspace_id=workspace.id,
                actor_id=actor.id,
                actor_email=actor.email,
                action=action,
                target_type=target_type,
                target_id=str(target_id),
                outcome="success",
                request_id=f"seed-{offset}",
                metadata_json={},
                created_at=detected + timedelta(minutes=offset),
            )
        )

    session.flush()
    return [incident, retries, search_outage]


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------
def seed_demo(session: Session, *, force: bool = False) -> SeedSummary:
    """Create (or reset) the demo workspace and return a summary of what exists."""
    existing = session.execute(
        select(Workspace).where(Workspace.slug == DEMO_WORKSPACE_SLUG)
    ).scalar_one_or_none()

    if existing is not None and not force:
        return SeedSummary(
            created=False,
            workspace_id=existing.id,
            workspace_name=existing.name,
        )

    if existing is not None:
        _reset_demo_workspace(session, existing)

    workspace, users = _seed_identity(session, existing)
    services, seeded_services = _seed_services(session, workspace, users["owner"])
    log_refs = _seed_logs(session, workspace, services)
    deployment = _seed_deployments(session, workspace, services)
    _rule, alerts = _seed_alerting(session, workspace, services, users["owner"])
    incidents = _seed_incidents(session, workspace, services, users, alerts, log_refs, deployment)
    session.flush()

    log_total = session.query(LogEvent).filter(LogEvent.workspace_id == workspace.id).count()
    summary = SeedSummary(
        created=True,
        workspace_id=workspace.id,
        workspace_name=workspace.name,
        accounts=[(_user_email(handle), role.value) for handle, _name, role in DEMO_USERS],
        service_keys=[(item.service.name, item.ingestion_key) for item in seeded_services],
        services=len(seeded_services),
        log_events=log_total,
        alerts=len(alerts),
        incidents=len(incidents),
    )
    return summary


def _print_summary(summary: SeedSummary) -> None:
    print()
    if not summary.created:
        print(f"Demo workspace '{summary.workspace_name}' already exists ({summary.workspace_id}).")
        print("Nothing to do. Re-run with --force to delete and reseed it.")
        return

    print(f"Seeded '{summary.workspace_name}' ({summary.workspace_id})")
    print(f"  services   : {summary.services}")
    print(f"  log events : {summary.log_events}")
    print(f"  alerts     : {summary.alerts}")
    print(f"  incidents  : {summary.incidents}")
    print()
    print("Sign in at http://localhost:5173 with any of:")
    for email, role in summary.accounts:
        print(f"  {email:<34} {role:<17} {DEMO_PASSWORD}")
    print()
    print("Ingestion keys (shown once; only the hash is stored):")
    for name, key in summary.service_keys:
        print(f"  {name:<16} {key}")
    print()
    print("Health checks are seeded disabled so the demo snapshot stays deterministic;")
    print("enable them once they point at a reachable endpoint.")
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed the OPERATION ZERO demo workspace.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="delete the existing demo workspace and reseed it",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress the summary output")
    args = parser.parse_args(argv)

    if settings.is_production:
        print(
            f"refusing to seed demo data while OZ_ENV={settings.env!r}; "
            "this script is for local and disposable environments only.",
            file=sys.stderr,
        )
        return 2

    _ensure_database_ready()
    _require_schema()

    session = SessionLocal()
    try:
        summary = seed_demo(session, force=args.force)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    if not args.quiet:
        _print_summary(summary)
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
