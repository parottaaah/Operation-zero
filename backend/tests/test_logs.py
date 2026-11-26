"""Structured log ingestion, redaction, idempotency and bounded search."""

from __future__ import annotations

from datetime import timedelta

from app.models.base import utcnow


def _ingest(client, service, events, **headers):
    return client.post(
        "/api/v1/ingest/logs",
        headers={"X-Ingestion-Key": service["ingestion_key"], **headers},
        json={"events": events},
    )


def test_ingest_and_search_logs(client, owner, create_service):
    service = create_service(owner)
    response = _ingest(
        client,
        service,
        [
            {
                "message": "checkout completed",
                "severity": "info",
                "attributes": {"order_id": "ord_123", "duration_ms": 82},
                "trace_id": "trace-1",
            },
            {"message": "payment gateway timeout", "severity": "error"},
        ],
    )
    assert response.status_code == 202, response.text
    assert response.json()["accepted"] == 2

    logs = client.get(owner.url("/logs"), headers=owner.headers)
    assert logs.status_code == 200
    body = logs.json()
    assert len(body["items"]) == 2
    assert body["items"][0]["service_name"] == "checkout-api"
    assert body["items"][0]["environment"] == "production"

    filtered = client.get(owner.url("/logs?severity=error"), headers=owner.headers)
    assert len(filtered.json()["items"]) == 1
    assert "timeout" in filtered.json()["items"][0]["message"]

    searched = client.get(owner.url("/logs?q=checkout"), headers=owner.headers)
    assert len(searched.json()["items"]) == 1


def test_ingestion_requires_valid_key(client, owner):
    missing = client.post("/api/v1/ingest/logs", json={"events": [{"message": "x"}]})
    assert missing.status_code == 401
    invalid = client.post(
        "/api/v1/ingest/logs",
        headers={"X-Ingestion-Key": "ozk_not-a-real-key"},
        json={"events": [{"message": "x"}]},
    )
    assert invalid.status_code == 401


def test_secrets_and_personal_data_are_redacted_before_persistence(client, owner, create_service):
    service = create_service(owner)
    response = _ingest(
        client,
        service,
        [
            {
                "message": (
                    "login failed for bob@example.com with password=hunter2 "
                    "authorization=Bearer abcdefghijklmnopqrstuvwxyz123456"
                ),
                "severity": "error",
                "attributes": {
                    "api_key": "sk-live-abcdefghijklmnopqrstuvwxyz",
                    "user": {"email": "bob@example.com", "password": "hunter2"},
                    "db_url": "postgresql://user:s3cretpass@db.internal:5432/app",
                    "safe_field": "visible",
                },
            }
        ],
    )
    body = response.json()
    assert body["accepted"] == 1
    assert body["redactions"] > 0

    stored = client.get(owner.url("/logs"), headers=owner.headers).json()["items"][0]
    blob = str(stored["message"]) + str(stored["attributes"])
    for secret in [
        "hunter2",
        "bob@example.com",
        "sk-live-abcdef",
        "s3cretpass",
        "abcdefghijklmnopqrstuvwxyz123456",
    ]:
        assert secret not in blob
    assert stored["attributes"]["safe_field"] == "visible"
    assert stored["attributes"]["api_key"] == "[REDACTED]"
    assert stored["redaction_count"] > 0
    assert stored["redacted_fields"]


def test_ingestion_idempotency_key_returns_cached_result(client, owner, create_service):
    service = create_service(owner)
    payload = [{"message": "only once", "idempotency_key": "evt-1"}]
    first = _ingest(client, service, payload, **{"Idempotency-Key": "batch-1"})
    assert first.status_code == 202
    assert first.json()["accepted"] == 1

    second = _ingest(client, service, payload, **{"Idempotency-Key": "batch-1"})
    assert second.status_code == 202
    assert second.json()["accepted"] == 1
    assert second.json()["event_ids"] == first.json()["event_ids"]

    # A different batch that re-sends the event key is counted as duplicate.
    third = _ingest(client, service, payload, **{"Idempotency-Key": "batch-2"})
    assert third.json()["accepted"] == 0
    assert third.json()["duplicates"] == 1

    total = client.get(owner.url("/logs"), headers=owner.headers).json()["items"]
    assert len(total) == 1


def test_batch_and_payload_limits(client, owner, create_service):
    service = create_service(owner)
    too_many = _ingest(client, service, [{"message": "x"} for _ in range(501)])
    assert too_many.status_code == 422

    big_attributes = {"blob": "a" * 15_000}
    oversized = _ingest(
        client,
        service,
        [{"message": "big", "attributes": big_attributes} for _ in range(30)],
    )
    assert oversized.status_code == 413

    nested = {"a": {"b": {"c": {"d": {"e": "too deep"}}}}}
    deep = _ingest(client, service, [{"message": "deep", "attributes": nested}])
    assert deep.status_code == 422


def test_future_and_old_timestamps_are_rejected(client, owner, create_service):
    service = create_service(owner)
    future = _ingest(
        client,
        service,
        [{"message": "from the future", "timestamp": (utcnow() + timedelta(days=2)).isoformat()}],
    )
    assert future.status_code == 422
    old = _ingest(
        client,
        service,
        [{"message": "ancient", "timestamp": (utcnow() - timedelta(days=60)).isoformat()}],
    )
    assert old.status_code == 422


def test_log_query_range_is_bounded(client, owner):
    start = (utcnow() - timedelta(days=30)).isoformat()
    response = client.get(owner.url(f"/logs?from_ts={start}"), headers=owner.headers)
    assert response.status_code == 422
    assert "range" in response.json()["error"]["message"]


def test_log_query_rejects_unknown_severity(client, owner):
    response = client.get(owner.url("/logs?severity=nope"), headers=owner.headers)
    assert response.status_code == 422
