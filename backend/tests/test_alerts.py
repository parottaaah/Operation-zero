"""Alert rule evaluation, deduplication, acknowledgement and incident conversion."""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest

from app.models import (
    Alert,
    AlertRule,
    AlertStatus,
    HealthCheck,
    HealthCheckResult,
    HealthResultStatus,
)
from app.models.base import utcnow
from app.services import ssrf


@pytest.fixture()
def allow_public_dns(monkeypatch):
    monkeypatch.setattr(
        ssrf,
        "validate_url",
        lambda url, allow_private=None: ssrf.ValidatedTarget(
            url=url, host="example.com", port=443, resolved_ips=("93.184.216.34",)
        ),
    )


def _service_with_check(client, owner, create_service):
    service = create_service(owner)
    response = client.put(
        f"{owner.url('/services')}/{service['id']}/health-check",
        headers=owner.headers,
        json={"url": "https://example.com/health", "interval_seconds": 60},
    )
    assert response.status_code == 200, response.text
    return service


def _seed_results(session_factory, workspace_id, service_id, statuses, latency=50.0, age_seconds=0):
    with session_factory() as session:
        hc = session.query(HealthCheck).filter(HealthCheck.service_id == uuid.UUID(service_id)).first()
        assert hc is not None
        ts = utcnow() - timedelta(seconds=age_seconds)
        for status in statuses:
            session.add(
                HealthCheckResult(
                    workspace_id=uuid.UUID(workspace_id),
                    service_id=uuid.UUID(service_id),
                    health_check_id=hc.id,
                    checked_at=ts,
                    status=status,
                    status_code=200 if status is HealthResultStatus.PASS else 503,
                    latency_ms=latency,
                    effective_status="healthy" if status is HealthResultStatus.PASS else "down",
                )
            )
        session.commit()


def _rule(client, owner, service_id, **overrides):
    payload = {
        "name": "Availability below 90%",
        "metric": "availability",
        "comparator": "lt",
        "threshold": 0.9,
        "service_id": service_id,
        "window_seconds": 600,
        "dedup_window_seconds": 1800,
        "severity": "critical",
        **overrides,
    }
    response = client.post(owner.url("/alert-rules"), headers=owner.headers, json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_rule_validation_rejects_impossible_threshold(client, owner, create_service):
    service = create_service(owner)
    response = client.post(
        owner.url("/alert-rules"),
        headers=owner.headers,
        json={
            "name": "Bad",
            "metric": "availability",
            "comparator": "lt",
            "threshold": 42,
            "service_id": service["id"],
            "window_seconds": 300,
        },
    )
    assert response.status_code == 422


def test_no_data_does_not_fire(client, owner, create_service):
    service = create_service(owner)
    _rule(client, owner, service["id"])
    result = client.post(owner.url("/alerts/evaluate"), headers=owner.headers)
    assert result.status_code == 200
    assert result.json()[0]["metric_value"] is None
    assert result.json()[0]["breached"] is False
    assert client.get(owner.url("/alerts"), headers=owner.headers).json()["items"] == []


def test_alert_fires_deduplicates_and_notifies(
    client, owner, create_service, session_factory, allow_public_dns
):
    service = _service_with_check(client, owner, create_service)
    rule = _rule(client, owner, service["id"])
    _seed_results(
        session_factory,
        owner.workspace_id,
        service["id"],
        [HealthResultStatus.FAIL, HealthResultStatus.FAIL],
    )

    first = client.post(owner.url("/alerts/evaluate"), headers=owner.headers).json()[0]
    assert first["breached"] is True
    assert first["action"] == "created"

    second = client.post(owner.url("/alerts/evaluate"), headers=owner.headers).json()[0]
    assert second["action"] == "deduplicated"

    alerts = client.get(owner.url("/alerts"), headers=owner.headers).json()["items"]
    assert len(alerts) == 1
    assert alerts[0]["occurrence_count"] == 2
    assert alerts[0]["severity"] == "critical"
    assert alerts[0]["notified_at"] is not None

    notifications = client.get(owner.url("/notifications"), headers=owner.headers).json()
    assert notifications
    assert notifications[0]["related_type"] == "alert"

    with session_factory() as session:
        rule_row = session.get(AlertRule, uuid.UUID(rule["id"]))
        assert rule_row.last_evaluated_at is not None


def test_acknowledge_mute_and_resolve(client, owner, create_service, session_factory, allow_public_dns):
    service = _service_with_check(client, owner, create_service)
    _rule(client, owner, service["id"])
    _seed_results(session_factory, owner.workspace_id, service["id"], [HealthResultStatus.FAIL])
    alert_id = client.post(owner.url("/alerts/evaluate"), headers=owner.headers).json()[0]["alert_id"]

    ack = client.post(
        f"{owner.url('/alerts')}/{alert_id}/acknowledge",
        headers=owner.headers,
        json={"note": "on it"},
    )
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"

    muted = client.post(
        f"{owner.url('/alerts')}/{alert_id}/mute",
        headers=owner.headers,
        json={"duration_minutes": 30, "reason": "maintenance"},
    )
    assert muted.status_code == 200
    assert muted.json()["status"] == "muted"
    assert muted.json()["muted_until"] is not None

    resolved = client.post(f"{owner.url('/alerts')}/{alert_id}/resolve", headers=owner.headers)
    assert resolved.status_code == 200
    assert resolved.json()["status"] == "resolved"


def test_alert_converts_to_incident_with_owner(
    client, owner, make_tenant, create_service, session_factory, allow_public_dns
):
    engineer = make_tenant(owner=owner, role="engineer")
    service = _service_with_check(client, owner, create_service)
    _rule(client, owner, service["id"])
    _seed_results(session_factory, owner.workspace_id, service["id"], [HealthResultStatus.FAIL])
    alert_id = client.post(owner.url("/alerts/evaluate"), headers=owner.headers).json()[0]["alert_id"]

    response = client.post(
        f"{owner.url('/alerts')}/{alert_id}/to-incident",
        headers=owner.headers,
        json={"owner_id": engineer.user_id, "summary": "Investigating elevated failures"},
    )
    assert response.status_code == 200, response.text
    incident_id = response.json()["incident_id"]

    detail = client.get(f"{owner.url('/incidents')}/{incident_id}", headers=owner.headers).json()
    assert detail["status"] == "open"
    assert detail["owner_id"] == engineer.user_id
    assert detail["alert_ids"] == [alert_id]
    assert any(event["event_type"] == "created" for event in detail["events"])
    assert any(link["kind"] == "note" for link in detail["evidence"])

    again = client.post(f"{owner.url('/alerts')}/{alert_id}/to-incident", headers=owner.headers, json={})
    assert again.status_code == 409


def test_error_count_rule_uses_logs(client, owner, create_service):
    service = create_service(owner)
    _rule(
        client,
        owner,
        service["id"],
        name="Too many errors",
        metric="error_count",
        comparator="gte",
        threshold=3,
        severity="warning",
    )
    response = client.post(
        "/api/v1/ingest/logs",
        headers={"X-Ingestion-Key": service["ingestion_key"]},
        json={
            "events": [
                {"message": "boom", "severity": "error"},
                {"message": "boom again", "severity": "critical"},
                {"message": "boom third", "severity": "error"},
            ]
        },
    )
    assert response.status_code == 202
    outcome = client.post(owner.url("/alerts/evaluate"), headers=owner.headers).json()[0]
    assert outcome["breached"] is True
    assert outcome["metric_value"] == 3.0


def test_auto_resolution_after_window(client, owner, create_service, session_factory, allow_public_dns):
    service = _service_with_check(client, owner, create_service)
    _rule(client, owner, service["id"], window_seconds=300)
    _seed_results(session_factory, owner.workspace_id, service["id"], [HealthResultStatus.FAIL])
    alert_id = client.post(owner.url("/alerts/evaluate"), headers=owner.headers).json()[0]["alert_id"]
    assert alert_id is not None

    with session_factory() as session:
        alert = session.get(Alert, uuid.UUID(alert_id))
        alert.last_seen_at = utcnow() - timedelta(minutes=30)
        session.query(HealthCheckResult).filter(
            HealthCheckResult.service_id == uuid.UUID(service["id"])
        ).update({HealthCheckResult.checked_at: utcnow() - timedelta(minutes=30)})
        session.commit()

    _seed_results(
        session_factory,
        owner.workspace_id,
        service["id"],
        [HealthResultStatus.PASS, HealthResultStatus.PASS],
        age_seconds=1,
    )
    outcome = client.post(owner.url("/alerts/evaluate"), headers=owner.headers).json()[0]
    assert outcome["breached"] is False
    assert outcome["action"] == "auto_resolved"

    with session_factory() as session:
        alert = session.get(Alert, uuid.UUID(alert_id))
        assert alert.status is AlertStatus.RESOLVED
        assert alert.resolved_at is not None


def test_viewer_can_read_alerts_but_not_acknowledge(client, owner, make_tenant):
    viewer = make_tenant(owner=owner, role="viewer")
    assert client.get(viewer.url("/alerts"), headers=viewer.headers).status_code == 200
    created = client.post(
        viewer.url("/alert-rules"),
        headers=viewer.headers,
        json={
            "name": "nope",
            "metric": "error_count",
            "comparator": "gt",
            "threshold": 1,
            "window_seconds": 300,
        },
    )
    assert created.status_code == 403
