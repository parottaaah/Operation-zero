"""Cursor pagination and malformed-cursor behaviour for every paginated list."""

from __future__ import annotations

import base64
import uuid
from datetime import timedelta

from app.models import (
    Alert,
    AlertMetric,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    AuditEvent,
    Comparator,
    WebhookEvent,
    WebhookStatus,
    utcnow,
)


def _collect_pages(client, url: str, headers: dict, limit: int) -> list[str]:
    ids: list[str] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    pages = 0

    while True:
        params: dict[str, object] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        response = client.get(url, headers=headers, params=params)
        assert response.status_code == 200, response.text
        body = response.json()
        assert len(body["items"]) <= limit
        ids.extend(item["id"] for item in body["items"])
        pages += 1
        assert pages < 20, "pagination did not terminate"

        cursor = body["next_cursor"]
        if cursor is None:
            assert body["has_more"] is False
            return ids

        assert body["has_more"] is True
        assert cursor not in seen_cursors, "cursor repeated"
        seen_cursors.add(cursor)


def _bad_cursors() -> list[str]:
    return [
        "not-a-cursor",
        base64.urlsafe_b64encode(b"no-pipe").decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(b"not-a-date|" + str(uuid.uuid4()).encode()).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(b"2026-01-01T00:00:00|not-a-uuid").decode("ascii").rstrip("="),
    ]


def _assert_malformed_cursor_is_4xx(client, url: str, headers: dict) -> None:
    for cursor in _bad_cursors():
        response = client.get(url, headers=headers, params={"limit": 2, "cursor": cursor})
        assert response.status_code == 422, (cursor, response.status_code, response.text)
        assert response.json()["error"]["code"] == "validation_failed"


def _workspace_uuid(tenant) -> uuid.UUID:
    return uuid.UUID(tenant.workspace_id)


def _seed_alerts(session_factory, workspace_id: uuid.UUID, count: int = 5) -> list[str]:
    base = utcnow()
    ids: list[str] = []
    with session_factory() as session:
        rule = AlertRule(
            workspace_id=workspace_id,
            name="Pagination rule",
            metric=AlertMetric.AVAILABILITY,
            comparator=Comparator.LT,
            threshold=0.9,
            window_seconds=300,
            severity=AlertSeverity.WARNING,
            enabled=True,
        )
        session.add(rule)
        session.flush()
        for index in range(count):
            alert = Alert(
                workspace_id=workspace_id,
                rule_id=rule.id,
                status=AlertStatus.FIRING,
                severity=AlertSeverity.WARNING,
                title=f"Alert {index}",
                description="",
                trigger_value=1.0,
                threshold=0.9,
                window_seconds=300,
                dedup_key=f"pagination-{index}",
                occurrence_count=1,
                first_seen_at=base - timedelta(minutes=index),
                last_seen_at=base - timedelta(minutes=index),
                created_at=base - timedelta(minutes=index),
                updated_at=base - timedelta(minutes=index),
            )
            session.add(alert)
            session.flush()
            ids.append(str(alert.id))
        session.commit()
    return ids


def _seed_audit_events(session_factory, workspace_id: uuid.UUID, count: int = 5) -> list[str]:
    base = utcnow()
    ids: list[str] = []
    with session_factory() as session:
        for index in range(count):
            event = AuditEvent(
                workspace_id=workspace_id,
                actor_email="pagination@example.com",
                action=f"pagination.action.{index}",
                target_type="pagination",
                target_id=str(index),
                outcome="success",
                request_id="",
                metadata_json={},
                created_at=base - timedelta(minutes=index),
            )
            session.add(event)
            session.flush()
            ids.append(str(event.id))
        session.commit()
    return ids


def _seed_deployment_events(session_factory, workspace_id: uuid.UUID, count: int = 5) -> list[str]:
    base = utcnow()
    ids: list[str] = []
    with session_factory() as session:
        for index in range(count):
            event = WebhookEvent(
                workspace_id=workspace_id,
                provider="github",
                delivery_id=f"pagination-delivery-{index}",
                body_sha256=None,
                event_type="push",
                action="",
                status=WebhookStatus.VERIFIED,
                signature_verified=True,
                reject_reason="",
                repository_full_name="acme/payments",
                commit_shas=[],
                pr_number=None,
                deployment_ref="",
                actor_login="",
                occurred_at=base - timedelta(minutes=index),
                received_at=base - timedelta(minutes=index),
                payload={},
            )
            session.add(event)
            session.flush()
            ids.append(str(event.id))
        session.commit()
    return ids


def test_services_cursor_pagination(client, owner, create_service):
    services = [create_service(owner, name=f"pagination-service-{index}") for index in range(5)]
    expected = {service["id"] for service in services}

    ids = _collect_pages(client, owner.url("/services"), owner.headers, limit=2)
    assert len(ids) == len(set(ids))
    assert set(ids) == expected

    _assert_malformed_cursor_is_4xx(client, owner.url("/services"), owner.headers)


def test_logs_cursor_pagination(client, owner, create_service):
    service = create_service(owner, name="pagination-log-service")
    base = utcnow()
    events = [
        {
            "message": f"pagination log {index}",
            "severity": "info",
            "timestamp": (base - timedelta(minutes=index + 1)).isoformat() + "Z",
        }
        for index in range(5)
    ]
    response = client.post(
        "/api/v1/ingest/logs",
        headers={"X-Ingestion-Key": service["ingestion_key"]},
        json={"events": events},
    )
    assert response.status_code == 202, response.text
    expected = set(response.json()["event_ids"])

    ids = _collect_pages(client, owner.url("/logs"), owner.headers, limit=2)
    assert len(ids) == len(set(ids))
    assert set(ids) == expected

    _assert_malformed_cursor_is_4xx(client, owner.url("/logs"), owner.headers)


def test_alerts_cursor_pagination(client, owner, session_factory):
    expected = set(_seed_alerts(session_factory, _workspace_uuid(owner)))

    ids = _collect_pages(client, owner.url("/alerts"), owner.headers, limit=2)
    assert len(ids) == len(set(ids))
    assert set(ids) == expected

    _assert_malformed_cursor_is_4xx(client, owner.url("/alerts"), owner.headers)


def test_audit_events_cursor_pagination(client, owner, session_factory):
    expected = set(_seed_audit_events(session_factory, _workspace_uuid(owner)))

    ids = _collect_pages(client, owner.url("/audit-events"), owner.headers, limit=2)
    assert len(ids) == len(set(ids))
    assert set(ids) == expected

    _assert_malformed_cursor_is_4xx(client, owner.url("/audit-events"), owner.headers)


def test_deployment_events_cursor_pagination(client, owner, session_factory):
    expected = set(_seed_deployment_events(session_factory, _workspace_uuid(owner)))

    ids = _collect_pages(client, owner.url("/deployment-events"), owner.headers, limit=2)
    assert len(ids) == len(set(ids))
    assert set(ids) == expected

    _assert_malformed_cursor_is_4xx(client, owner.url("/deployment-events"), owner.headers)
