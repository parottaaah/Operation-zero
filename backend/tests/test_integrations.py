"""GitHub integration: OAuth connect, webhook verification and deployment context."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from app.core.config import settings

WEBHOOK_SECRET = "test-webhook-secret"


@pytest.fixture()
def fake_github(monkeypatch):
    async def exchange_code(code, state, **kwargs):
        return {
            "access_token": "ghs_fake_token_value",
            "scope": "repo:status",
            "token_type": "bearer",
        }

    async def fetch_account(token, **kwargs):
        return {"login": "acme-bot", "id": 4242}

    async def fetch_repository(token, full_name, **kwargs):
        if full_name != "acme/payments":
            return None
        return {"full_name": "acme/payments", "id": 99, "default_branch": "main", "private": True}

    monkeypatch.setattr("app.services.github.exchange_code", exchange_code)
    monkeypatch.setattr("app.services.github.fetch_account", fetch_account)
    monkeypatch.setattr("app.services.github.fetch_repository", fetch_repository)


def connect(client, tenant, repository="acme/payments"):
    response = client.post(
        tenant.url("/integrations/github/connect"),
        headers=tenant.headers,
        json={"repository_full_name": repository},
    )
    assert response.status_code == 201, response.text
    return response.json()


def do_callback(client, authorize_url):
    state = authorize_url.split("state=")[1].split("&")[0]
    return client.get(
        f"/api/v1/integrations/github/callback?code=test-code&state={state}",
        follow_redirects=False,
    )


def signed_headers(body: bytes, delivery="delivery-1", event="push"):
    signature = "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-Hub-Signature-256": signature,
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "Content-Type": "application/json",
    }


def test_connect_returns_scopes_and_data_notice(client, owner, fake_github):
    body = connect(client, owner)
    assert "authorize_url" in body
    assert "state=" in body["authorize_url"]
    assert body["scopes"] == ["read:user", "repo:status"]
    assert "encrypted at rest" in body["data_processing_notice"]

    integrations = client.get(owner.url("/integrations"), headers=owner.headers).json()
    assert len(integrations) == 1
    assert integrations[0]["status"] == "pending"
    assert "secret" not in json.dumps(integrations[0]).lower()


def test_connect_unavailable_when_not_configured(client, owner, monkeypatch):
    monkeypatch.setattr(settings, "github_client_id", "")
    response = client.post(
        owner.url("/integrations/github/connect"),
        headers=owner.headers,
        json={"repository_full_name": "acme/payments"},
    )
    assert response.status_code == 503


def test_oauth_callback_completes_integration(client, owner, fake_github):
    body = connect(client, owner)
    response = do_callback(client, body["authorize_url"])
    assert response.status_code in (302, 307)
    assert "status=connected" in response.headers["location"]

    integrations = client.get(owner.url("/integrations"), headers=owner.headers).json()
    integration = integrations[0]
    assert integration["status"] == "connected"
    assert integration["external_account"] == "acme-bot"
    assert integration["repository_full_name"] == "acme/payments"
    assert integration["config"]["webhook_url"].endswith("/api/v1/webhooks/github")
    assert "secret" not in json.dumps(integration).lower()

    audit = client.get(owner.url("/audit-events?action=integration.github.connected"), headers=owner.headers)
    assert audit.json()["items"]


def test_oauth_callback_rejects_replayed_state(client, owner, fake_github):
    body = connect(client, owner)
    first = do_callback(client, body["authorize_url"])
    assert "status=connected" in first.headers["location"]
    second = do_callback(client, body["authorize_url"])
    assert "status=error" in second.headers["location"]


def test_integration_test_endpoint(client, owner, fake_github):
    body = connect(client, owner)
    do_callback(client, body["authorize_url"])
    integration_id = client.get(owner.url("/integrations"), headers=owner.headers).json()[0]["id"]
    result = client.post(f"{owner.url('/integrations')}/{integration_id}/test", headers=owner.headers)
    assert result.status_code == 200
    assert result.json()["ok"] is True
    assert result.json()["account"] == "acme-bot"


def test_webhook_requires_valid_signature(client, owner, fake_github):
    body = connect(client, owner)
    do_callback(client, body["authorize_url"])
    payload = json.dumps(
        {"ref": "refs/heads/main", "after": "abc123", "repository": {"full_name": "acme/payments"}}
    ).encode()

    missing = client.post("/api/v1/webhooks/github", content=payload)
    assert missing.status_code == 401

    bad_signature = client.post(
        "/api/v1/webhooks/github",
        content=payload,
        headers={
            "X-Hub-Signature-256": "sha256=deadbeef",
            "X-GitHub-Event": "push",
            "X-GitHub-Delivery": "delivery-x",
            "Content-Type": "application/json",
        },
    )
    assert bad_signature.status_code == 401

    # No persisted events for rejected requests.
    deployments = client.get(owner.url("/deployments"), headers=owner.headers).json()
    assert deployments["events"] == []


def test_verified_webhook_is_stored_and_deduplicated(client, owner, fake_github):
    body = connect(client, owner)
    do_callback(client, body["authorize_url"])
    payload = {
        "ref": "refs/heads/main",
        "after": "abc123def456",
        "commits": [{"id": "abc123def456", "timestamp": "2026-11-26T10:00:00Z"}],
        "repository": {"full_name": "acme/payments"},
        "sender": {"login": "dev-acme"},
        "head_commit": {"timestamp": "2026-11-26T10:00:00Z"},
    }
    raw = json.dumps(payload).encode()

    first = client.post("/api/v1/webhooks/github", content=raw, headers=signed_headers(raw, "delivery-1"))
    assert first.status_code == 202
    assert first.json()["status"] == "verified"

    duplicate = client.post("/api/v1/webhooks/github", content=raw, headers=signed_headers(raw, "delivery-1"))
    assert duplicate.status_code == 202
    assert duplicate.json()["status"] == "duplicate"
    assert duplicate.json()["event_id"] == first.json()["event_id"]

    deployments = client.get(owner.url("/deployments"), headers=owner.headers).json()
    assert len(deployments["events"]) == 1
    event = deployments["events"][0]
    assert event["event_type"] == "push"
    assert event["signature_verified"] is True
    assert event["commit_shas"] == ["abc123def456"]
    assert event["repository_full_name"] == "acme/payments"

    integration = client.get(owner.url("/integrations"), headers=owner.headers).json()[0]
    assert integration["last_event_at"] is not None


def test_webhook_for_unknown_repository_is_ignored(client, owner, fake_github):
    body = connect(client, owner)
    do_callback(client, body["authorize_url"])
    raw = json.dumps({"repository": {"full_name": "other/repo"}}).encode()
    response = client.post("/api/v1/webhooks/github", content=raw, headers=signed_headers(raw, "delivery-2"))
    assert response.status_code == 202
    assert response.json()["status"] == "ignored"
    assert client.get(owner.url("/deployments"), headers=owner.headers).json()["events"] == []


def test_webhook_config_endpoint(client, owner):
    response = client.get(owner.url("/integrations/github/webhook-config"), headers=owner.headers)
    assert response.status_code == 200
    body = response.json()
    assert body["webhook_url"].endswith("/api/v1/webhooks/github")
    assert body["secret_configured"] is True


def test_revoke_integration(client, owner, fake_github):
    body = connect(client, owner)
    do_callback(client, body["authorize_url"])
    integration_id = client.get(owner.url("/integrations"), headers=owner.headers).json()[0]["id"]
    revoked = client.delete(f"{owner.url('/integrations')}/{integration_id}", headers=owner.headers)
    assert revoked.status_code == 200
    integrations = client.get(owner.url("/integrations"), headers=owner.headers).json()
    assert integrations[0]["status"] == "revoked"
    assert integrations[0]["revoked_at"] is not None


def test_engineer_cannot_connect_integration(client, owner, make_tenant, fake_github):
    engineer = make_tenant(owner=owner, role="engineer")
    response = client.post(
        engineer.url("/integrations/github/connect"),
        headers=engineer.headers,
        json={"repository_full_name": "acme/payments"},
    )
    assert response.status_code == 403
