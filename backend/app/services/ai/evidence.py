"""Evidence pack construction for AI investigation.

Only tenant-scoped, already-redacted records are used. Every item receives a stable
``E<n>`` identifier that the UI can resolve back to a stored record.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.models.ai import AIAnalysis
from app.models.alerting import Alert
from app.models.identity import Workspace
from app.models.incident import EvidenceKind, EvidenceLink, Incident
from app.models.integration import WebhookEvent
from app.models.service import HealthCheckResult, Service
from app.models.telemetry import LogEvent, Severity
from app.services.ai.prompts import EvidenceItem, sanitize_text

MAX_LOGS = 12
MAX_HEALTH_RESULTS = 10
MAX_WEBHOOKS = 5
MAX_TIMELINE = 10
MAX_MANUAL_EVIDENCE = 5
MAX_ALERTS = 5


def _iso(value) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ") if value else ""


def build_evidence_pack(session: Session, incident: Incident) -> tuple[list[EvidenceItem], dict]:
    workspace = session.get(Workspace, incident.workspace_id)
    service = session.get(Service, incident.service_id) if incident.service_id else None
    evidence: list[EvidenceItem] = []

    def add(
        kind: str,
        timestamp,
        summary: str,
        *,
        ref_id=None,
        url: str = "",
        data: dict | None = None,
    ) -> str | None:
        if len(evidence) >= 60:
            return None
        item_id = f"E{len(evidence) + 1}"
        evidence.append(
            EvidenceItem(
                id=item_id,
                kind=kind,
                timestamp=_iso(timestamp),
                summary=sanitize_text(summary),
                ref_id=str(ref_id) if ref_id else None,
                url=url,
                data=data or {},
            )
        )
        return item_id

    context = {
        "title": incident.title,
        "status": incident.status.value,
        "severity": incident.severity.value,
        "service": service.name if service else "unknown",
        "detected_at": _iso(incident.detected_at),
    }

    if service is not None:
        add(
            "service",
            service.last_checked_at,
            f"Service {service.name} ({service.environment.value}) status is "
            f"{service.status.value}; last health check {_iso(service.last_checked_at)}.",
            ref_id=service.id,
            url=f"/services/{service.id}",
            data={"status": service.status.value},
        )

    alerts = (
        session.query(Alert)
        .filter(Alert.incident_id == incident.id)
        .order_by(Alert.created_at.desc())
        .limit(MAX_ALERTS)
        .all()
    )
    for alert in alerts:
        add(
            "alert",
            alert.first_seen_at,
            f"Alert '{alert.title}' fired with observed {alert.trigger_value:.4g} against "
            f"threshold {alert.threshold:.4g} over {alert.window_seconds}s; "
            f"occurrences {alert.occurrence_count}; status {alert.status.value}.",
            ref_id=alert.id,
            data={"severity": alert.severity.value},
        )

    window_start = incident.detected_at - timedelta(minutes=30)
    window_end = incident.resolved_at or incident.closed_at or incident.detected_at + timedelta(hours=24)

    health_query = session.query(HealthCheckResult).filter(
        HealthCheckResult.workspace_id == incident.workspace_id,
        HealthCheckResult.checked_at >= window_start,
        HealthCheckResult.checked_at <= window_end,
    )
    if incident.service_id:
        health_query = health_query.filter(HealthCheckResult.service_id == incident.service_id)
    health_results = (
        health_query.order_by(HealthCheckResult.checked_at.desc()).limit(MAX_HEALTH_RESULTS).all()
    )
    pass_count = sum(1 for r in health_results if r.status.value == "pass")
    for result in reversed(health_results):
        add(
            "health_check_result",
            result.checked_at,
            f"Health check {result.status.value} with HTTP {result.status_code} in "
            f"{result.latency_ms:.0f} ms{(' — ' + result.error_message) if result.error_message else ''}.",
            ref_id=result.id,
            url=f"/services/{result.service_id}",
            data={"effective_status": result.effective_status.value},
        )
    if health_results:
        add(
            "metric",
            health_results[0].checked_at,
            f"Of the {len(health_results)} most recent health checks in the incident window, "
            f"{pass_count} passed and {len(health_results) - pass_count} did not.",
            data={"pass": pass_count, "total": len(health_results)},
        )

    log_query = session.query(LogEvent).filter(
        LogEvent.workspace_id == incident.workspace_id,
        LogEvent.event_timestamp >= window_start,
        LogEvent.event_timestamp <= window_end,
    )
    if incident.service_id:
        log_query = log_query.filter(LogEvent.service_id == incident.service_id)
    logs = log_query.order_by(LogEvent.event_timestamp.desc()).limit(MAX_LOGS).all()
    for log in reversed(logs):
        add(
            "log_event",
            log.event_timestamp,
            f"[{log.severity.value}] {log.message}",
            ref_id=log.id,
            url=f"/logs?event={log.id}",
            data={"service_id": str(log.service_id) if log.service_id else ""},
        )
    error_logs = [log for log in logs if log.severity in (Severity.ERROR, Severity.CRITICAL)]
    if error_logs:
        add(
            "metric",
            error_logs[0].event_timestamp,
            f"{len(error_logs)} of the {len(logs)} sampled log events are error or critical severity.",
            data={"errors": len(error_logs), "sampled": len(logs)},
        )

    webhooks = (
        session.query(WebhookEvent)
        .filter(
            WebhookEvent.workspace_id == incident.workspace_id,
            WebhookEvent.status == "verified",
            WebhookEvent.occurred_at >= window_start,
            WebhookEvent.occurred_at <= window_end,
        )
        .order_by(WebhookEvent.occurred_at.desc())
        .limit(MAX_WEBHOOKS)
        .all()
    )
    for hook in reversed(webhooks):
        add(
            "webhook_event",
            hook.occurred_at,
            f"Verified GitHub {hook.event_type} event from {hook.actor_login or 'unknown'} on "
            f"{hook.repository_full_name}: {hook.deployment_ref or hook.action or ''} "
            f"{', '.join(hook.commit_shas[:3])}",
            ref_id=hook.id,
            url=f"/deployments?event={hook.id}",
            data={"action": hook.action},
        )

    manual = (
        session.query(EvidenceLink)
        .filter(EvidenceLink.incident_id == incident.id)
        .order_by(EvidenceLink.created_at.desc())
        .limit(MAX_MANUAL_EVIDENCE)
        .all()
    )
    for link in reversed(manual):
        if link.kind in (
            EvidenceKind.LOG_EVENT,
            EvidenceKind.HEALTH_CHECK_RESULT,
            EvidenceKind.WEBHOOK_EVENT,
        ):
            continue  # already represented by the underlying record
        add(
            "evidence",
            link.created_at,
            f"{link.title or link.kind.value}: {link.excerpt}",
            ref_id=link.id,
            url=link.url,
        )

    from app.models.incident import IncidentEvent

    events = (
        session.query(IncidentEvent)
        .filter(IncidentEvent.incident_id == incident.id)
        .order_by(IncidentEvent.created_at.desc())
        .limit(MAX_TIMELINE)
        .all()
    )
    for event in reversed(events):
        add(
            "incident_event",
            event.created_at,
            f"{event.actor_label}: {event.message}",
            ref_id=event.id,
        )

    context["workspace"] = workspace.name if workspace else ""
    context["service_id"] = str(incident.service_id) if incident.service_id else None
    return evidence, context


def sources_index(evidence: list[EvidenceItem]) -> dict[str, dict]:
    return {
        item.id: {
            "kind": item.kind,
            "ref_id": item.ref_id,
            "url": item.url,
            "timestamp": item.timestamp,
            "label": item.summary[:160],
        }
        for item in evidence
    }


def latest_completed_analysis(session: Session, incident_id) -> AIAnalysis | None:
    return (
        session.query(AIAnalysis)
        .filter(AIAnalysis.incident_id == incident_id, AIAnalysis.status == "completed")
        .order_by(AIAnalysis.created_at.desc())
        .first()
    )


__all__ = ["build_evidence_pack", "sources_index", "latest_completed_analysis"]
