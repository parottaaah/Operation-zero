"""Tenant isolation and server-side RBAC."""

from __future__ import annotations

from app.models import Role


def test_cross_workspace_access_is_404(client, make_tenant, create_service):
    alice = make_tenant(workspace_name="Alpha")
    bob = make_tenant(workspace_name="Beta")
    service = create_service(alice)

    response = client.get(
        f"/api/v1/workspaces/{alice.workspace_id}/services/{service['id']}",
        headers=bob.headers,
    )
    assert response.status_code == 404

    response = client.get(alice.url("/services"), headers=bob.headers)
    assert response.status_code == 404

    response = client.get(alice.url("/logs"), headers=bob.headers)
    assert response.status_code == 404

    response = client.get(alice.url("/audit-events"), headers=bob.headers)
    assert response.status_code == 404


def test_viewer_cannot_read_raw_telemetry_or_write(client, make_tenant, create_service):
    owner = make_tenant(workspace_name="Gamma")
    viewer = make_tenant(owner=owner, role=Role.VIEWER)
    service = create_service(owner)

    logs = client.get(viewer.url("/logs"), headers=viewer.headers)
    assert logs.status_code == 403

    create = client.post(
        viewer.url("/services"),
        headers=viewer.headers,
        json={"name": "sneaky", "environment": "production"},
    )
    assert create.status_code == 403

    # Viewer can still read the service inventory and export reports.
    assert client.get(viewer.url("/services"), headers=viewer.headers).status_code == 200
    assert service["name"] == "checkout-api"


def test_engineer_cannot_manage_members(client, make_tenant, owner):
    engineer = make_tenant(owner=owner, role=Role.ENGINEER)
    response = client.get(owner.url("/members"), headers=engineer.headers)
    assert response.status_code == 200
    invite = client.post(
        owner.url("/members"),
        headers=engineer.headers,
        json={"email": "someone@example.com", "role": "viewer"},
    )
    assert invite.status_code == 403


def test_admin_cannot_grant_owner(client, make_tenant, owner):
    admin = make_tenant(owner=owner, role=Role.ADMIN)
    newcomer = make_tenant()
    response = client.post(
        owner.url("/members"),
        headers=admin.headers,
        json={"email": newcomer.email, "role": "owner"},
    )
    assert response.status_code == 403


def test_owner_can_promote_member_and_audit_is_recorded(client, make_tenant, owner):
    member = make_tenant(owner=owner, role=Role.VIEWER)
    response = client.patch(
        f"{owner.url('/members')}/{member.user_id}",
        headers=owner.headers,
        json={"role": "engineer"},
    )
    assert response.status_code == 200
    assert response.json()["role"] == "engineer"

    audit = client.get(owner.url("/audit-events?action=member.role_change"), headers=owner.headers)
    assert audit.status_code == 200
    actions = [item["action"] for item in audit.json()["items"]]
    assert "member.role_change" in actions


def test_last_owner_cannot_be_demoted_or_removed(client, owner):
    demote = client.patch(
        f"{owner.url('/members')}/{owner.user_id}",
        headers=owner.headers,
        json={"role": "admin"},
    )
    assert demote.status_code == 409

    remove = client.delete(f"{owner.url('/members')}/{owner.user_id}", headers=owner.headers)
    assert remove.status_code == 409


def test_workspace_deletion_requires_slug_confirmation(client, owner):
    workspace = client.get(f"/api/v1/workspaces/{owner.workspace_id}", headers=owner.headers).json()
    wrong = client.delete(f"/api/v1/workspaces/{owner.workspace_id}?confirm=nope", headers=owner.headers)
    assert wrong.status_code == 422
    ok = client.delete(
        f"/api/v1/workspaces/{owner.workspace_id}?confirm={workspace['slug']}",
        headers=owner.headers,
    )
    assert ok.status_code == 200
    assert client.get(f"/api/v1/workspaces/{owner.workspace_id}", headers=owner.headers).status_code == 404


def test_settings_update_requires_admin(client, make_tenant, owner):
    viewer = make_tenant(owner=owner, role=Role.VIEWER)
    denied = client.patch(
        f"/api/v1/workspaces/{owner.workspace_id}",
        headers=viewer.headers,
        json={"name": "Renamed"},
    )
    assert denied.status_code == 403
    allowed = client.patch(
        f"/api/v1/workspaces/{owner.workspace_id}",
        headers=owner.headers,
        json={"telemetry_retention_days": 14},
    )
    assert allowed.status_code == 200
    assert allowed.json()["telemetry_retention_days"] == 14


def test_overview_returns_control_room_data(client, owner, create_service):
    create_service(owner)
    response = client.get(owner.url("/overview"), headers=owner.headers)
    assert response.status_code == 200
    body = response.json()
    assert body["workspace"]["id"] == owner.workspace_id
    assert body["services"]["unknown"] == 1
    assert "ingestion" in body and "ai" in body


def test_create_workspace_endpoint_creates_owner_membership(client, owner):
    response = client.post(
        "/api/v1/workspaces",
        headers=owner.headers,
        json={"name": "Second Workspace"},
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["name"] == "Second Workspace"
    assert created["role"] == "owner"

    workspaces = client.get("/api/v1/workspaces", headers=owner.headers).json()
    assert {workspace["id"] for workspace in workspaces} >= {owner.workspace_id, created["id"]}

    audit = client.get(
        f"/api/v1/workspaces/{created['id']}/audit-events?action=workspace.create",
        headers=owner.headers,
    )
    assert audit.status_code == 200
    assert audit.json()["items"]
