"""Service registry and health-check behaviour, including SSRF controls."""

from __future__ import annotations

import pytest

from app.core.errors import SsrfBlocked
from app.services import ssrf
from app.services.ssrf import FetchOutcome


@pytest.fixture()
def allow_public_dns(monkeypatch):
    monkeypatch.setattr(
        ssrf,
        "validate_url",
        lambda url, allow_private=None: ssrf.ValidatedTarget(
            url=url, host="example.com", port=443, resolved_ips=("93.184.216.34",)
        ),
    )


def test_create_service_returns_ingestion_key_once(client, owner):
    response = client.post(
        owner.url("/services"),
        headers=owner.headers,
        json={"name": "checkout-api", "environment": "production"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["ingestion_key"].startswith("ozk_")
    assert body["ingestion_key_last4"] == body["ingestion_key"][-4:]

    detail = client.get(f"{owner.url('/services')}/{body['id']}", headers=owner.headers)
    assert detail.status_code == 200
    assert "ingestion_key" not in detail.json()


def test_duplicate_service_name_in_same_environment_conflicts(client, owner, create_service):
    create_service(owner)
    duplicate = client.post(
        owner.url("/services"),
        headers=owner.headers,
        json={"name": "checkout-api", "environment": "production"},
    )
    assert duplicate.status_code == 409
    other_env = client.post(
        owner.url("/services"),
        headers=owner.headers,
        json={"name": "checkout-api", "environment": "staging"},
    )
    assert other_env.status_code == 201


def test_health_check_rejects_private_and_metadata_targets(client, owner, create_service):
    service = create_service(owner)
    for url in [
        "http://127.0.0.1:8080/health",
        "http://localhost/health",
        "http://169.254.169.254/latest/meta-data",
        "ftp://example.com/health",
        "http://user:pass@example.com/health",
    ]:
        response = client.put(
            f"{owner.url('/services')}/{service['id']}/health-check",
            headers=owner.headers,
            json={"url": url, "interval_seconds": 60, "timeout_seconds": 5},
        )
        assert response.status_code == 400, url
        assert response.json()["error"]["code"] == "ssrf_blocked"


def test_ssrf_validator_unit_rules(monkeypatch):
    monkeypatch.setattr(ssrf.settings, "allow_private_health_checks", False)
    for blocked in [
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://192.168.1.10/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://169.254.169.254/",
        "http://metadata.google.internal/",
        "http://service.local/",
        "file:///etc/passwd",
    ]:
        with pytest.raises(SsrfBlocked):
            ssrf.validate_url(blocked)

    monkeypatch.setattr(ssrf, "resolve_host", lambda host, port: ("93.184.216.34",))
    target = ssrf.validate_url("https://example.com/health")
    assert target.host == "example.com"
    assert target.resolved_ips == ("93.184.216.34",)

    monkeypatch.setattr(ssrf, "resolve_host", lambda host, port: ("127.0.0.1",))
    with pytest.raises(SsrfBlocked):
        ssrf.validate_url("https://rebind.example.com/health")


def test_health_check_lifecycle_and_state_thresholds(
    client, owner, create_service, allow_public_dns, monkeypatch
):
    service = create_service(owner)
    configure = client.put(
        f"{owner.url('/services')}/{service['id']}/health-check",
        headers=owner.headers,
        json={
            "url": "https://example.com/health",
            "interval_seconds": 60,
            "timeout_seconds": 5,
            "failure_threshold": 2,
            "recovery_threshold": 1,
        },
    )
    assert configure.status_code == 200

    async def failing(*args, **kwargs):
        return FetchOutcome(status_code=503, latency_ms=12.5, error_kind="", error_message="")

    monkeypatch.setattr("app.services.healthcheck.safe_fetch", failing)
    first = client.post(f"{owner.url('/services')}/{service['id']}/health-check/run", headers=owner.headers)
    assert first.status_code == 200
    assert first.json()["service_status"] == "degraded"
    assert first.json()["result"]["status"] == "fail"

    second = client.post(f"{owner.url('/services')}/{service['id']}/health-check/run", headers=owner.headers)
    assert second.json()["service_status"] == "down"

    async def passing(*args, **kwargs):
        return FetchOutcome(status_code=200, latency_ms=8.0)

    monkeypatch.setattr("app.services.healthcheck.safe_fetch", passing)
    third = client.post(f"{owner.url('/services')}/{service['id']}/health-check/run", headers=owner.headers)
    assert third.json()["service_status"] == "healthy"

    history = client.get(f"{owner.url('/services')}/{service['id']}/health?hours=1", headers=owner.headers)
    assert history.status_code == 200
    body = history.json()
    assert len(body["results"]) == 3
    assert body["availability"] == pytest.approx(1 / 3, abs=0.01)
    assert body["p95_latency_ms"] is not None


def test_health_check_timeout_maps_to_timeout_status(
    client, owner, create_service, allow_public_dns, monkeypatch
):
    service = create_service(owner)
    client.put(
        f"{owner.url('/services')}/{service['id']}/health-check",
        headers=owner.headers,
        json={"url": "https://example.com/health"},
    )

    async def timeout(*args, **kwargs):
        return FetchOutcome(
            status_code=None,
            latency_ms=5000,
            error_kind="timeout",
            error_message="request timed out",
        )

    monkeypatch.setattr("app.services.healthcheck.safe_fetch", timeout)
    response = client.post(
        f"{owner.url('/services')}/{service['id']}/health-check/run", headers=owner.headers
    )
    assert response.status_code == 200
    assert response.json()["result"]["status"] == "timeout"


def test_ingestion_key_rotation_invalidates_old_key(client, owner, create_service):
    service = create_service(owner)
    old_key = service["ingestion_key"]
    rotated = client.post(
        f"{owner.url('/services')}/{service['id']}/ingestion-key/rotate", headers=owner.headers
    )
    assert rotated.status_code == 200
    new_key = rotated.json()["ingestion_key"]
    assert new_key != old_key

    old_attempt = client.post(
        "/api/v1/ingest/logs",
        headers={"X-Ingestion-Key": old_key},
        json={"events": [{"message": "hello"}]},
    )
    assert old_attempt.status_code == 401
    new_attempt = client.post(
        "/api/v1/ingest/logs",
        headers={"X-Ingestion-Key": new_key},
        json={"events": [{"message": "hello"}]},
    )
    assert new_attempt.status_code == 202


def test_delete_service_blocked_by_active_incident(client, owner, create_service):
    service = create_service(owner)
    incident = client.post(
        owner.url("/incidents"),
        headers=owner.headers,
        json={"title": "Active issue", "service_id": service["id"]},
    )
    assert incident.status_code == 201
    response = client.delete(f"{owner.url('/services')}/{service['id']}", headers=owner.headers)
    assert response.status_code == 409
