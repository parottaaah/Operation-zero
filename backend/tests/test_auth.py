"""Authentication and profile behaviour."""

from __future__ import annotations

from tests.conftest import VALID_PASSWORD


def test_register_login_and_me(client, make_tenant):
    tenant = make_tenant(workspace_name="Orbit Labs")
    assert tenant.workspace_id

    me = client.get("/api/v1/auth/me", headers=tenant.headers)
    assert me.status_code == 200
    body = me.json()
    assert body["user"]["email"] == tenant.email
    assert body["memberships"][0]["role"] == "owner"
    assert body["memberships"][0]["workspace_name"] == "Orbit Labs"

    login = client.post("/api/v1/auth/login", json={"email": tenant.email, "password": VALID_PASSWORD})
    assert login.status_code == 200
    tokens = login.json()
    assert tokens["token_type"] == "bearer"
    assert tokens["access_token"]


def test_login_rejects_bad_password(client, make_tenant):
    tenant = make_tenant()
    response = client.post("/api/v1/auth/login", json={"email": tenant.email, "password": "WrongPassword1"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_duplicate_registration_conflicts(client, make_tenant):
    tenant = make_tenant()
    response = client.post(
        "/api/v1/auth/register",
        json={"email": tenant.email, "password": VALID_PASSWORD, "full_name": "Dup"},
    )
    assert response.status_code == 409


def test_weak_password_is_rejected(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": "short", "full_name": "Weak"},
    )
    assert response.status_code == 422


def test_missing_token_is_unauthenticated(client):
    response = client.get("/api/v1/workspaces")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_refresh_token_rotation(client, make_tenant):
    tenant = make_tenant()
    login = client.post("/api/v1/auth/login", json={"email": tenant.email, "password": VALID_PASSWORD}).json()
    refreshed = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert refreshed.status_code == 200
    new_token = refreshed.json()["access_token"]
    assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_token}"}).status_code == 200


def test_refresh_rejects_access_token(client, make_tenant):
    tenant = make_tenant()
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": tenant.access_token})
    assert response.status_code == 401


def test_security_headers_and_request_id(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["X-Request-ID"]

    requested = client.get("/healthz", headers={"X-Request-ID": "trace-abc"})
    assert requested.headers["X-Request-ID"] == "trace-abc"


def test_openapi_contract_contains_mvp_surface(client):
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]

    # Every core path and method from PRD §9, using the real workspace-scoped
    # paths emitted by FastAPI. Auth registration is included as a prerequisite.
    required = [
        ("post", "/api/v1/auth/register"),
        ("post", "/api/v1/workspaces"),
        ("get", "/api/v1/workspaces/{workspace_id}"),
        ("post", "/api/v1/workspaces/{workspace_id}/services"),
        ("get", "/api/v1/workspaces/{workspace_id}/services"),
        ("get", "/api/v1/workspaces/{workspace_id}/services/{service_id}/health"),
        ("post", "/api/v1/ingest/logs"),
        ("get", "/api/v1/workspaces/{workspace_id}/logs"),
        ("post", "/api/v1/workspaces/{workspace_id}/alert-rules"),
        ("get", "/api/v1/workspaces/{workspace_id}/alerts"),
        ("post", "/api/v1/workspaces/{workspace_id}/alerts/{alert_id}/acknowledge"),
        ("post", "/api/v1/workspaces/{workspace_id}/incidents"),
        ("get", "/api/v1/workspaces/{workspace_id}/incidents/{incident_id}"),
        ("patch", "/api/v1/workspaces/{workspace_id}/incidents/{incident_id}"),
        ("post", "/api/v1/workspaces/{workspace_id}/incidents/{incident_id}/evidence"),
        ("post", "/api/v1/workspaces/{workspace_id}/incidents/{incident_id}/ai-analysis"),
        ("post", "/api/v1/workspaces/{workspace_id}/integrations/github/connect"),
        ("post", "/api/v1/webhooks/github"),
        ("get", "/api/v1/workspaces/{workspace_id}/audit-events"),
    ]
    for method, path in required:
        assert path in paths, path
        assert method in paths[path], f"{method.upper()} {path}"
    assert spec["info"]["title"] == "OPERATION ZERO"
