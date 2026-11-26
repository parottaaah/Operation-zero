"""Test fixtures: isolated SQLite database, TestClient and tenant helpers."""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.core.db import get_db
from app.core.rate_limit import reset_rate_limiter_state
from app.main import app
from app.models import Base, Role

VALID_PASSWORD = "CorrectHorse9"


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)


@pytest.fixture()
def db(session_factory) -> Iterator[Session]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(engine, session_factory, monkeypatch) -> Iterator[TestClient]:
    def override_get_db():
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(settings, "env", "test")
    monkeypatch.setattr(settings, "redis_url", "")
    monkeypatch.setattr(settings, "github_webhook_secret", "test-webhook-secret")
    monkeypatch.setattr(settings, "github_client_id", "test-client")
    monkeypatch.setattr(settings, "github_client_secret", "test-client-secret")
    monkeypatch.setattr(settings, "reports_dir", "./data/test-reports")
    reset_rate_limiter_state()
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    reset_rate_limiter_state()


class Tenant:
    """A registered user plus their workspace, ready for authenticated calls."""

    def __init__(self, data: dict) -> None:
        self.headers: dict[str, str] = data["headers"]
        self.workspace_id: str = data["workspace_id"]
        self.user_id: str = data["user_id"]
        self.email: str = data["email"]
        self.access_token: str = data["access_token"]

    def url(self, path: str) -> str:
        return f"/api/v1/workspaces/{self.workspace_id}{path}"


@pytest.fixture()
def make_tenant(client: TestClient):
    counter = {"n": 0}

    def _make(
        *,
        workspace_name: str = "Acme",
        email: str | None = None,
        role: Role | None = None,
        owner: Tenant | None = None,
    ) -> Tenant:
        counter["n"] += 1
        email = email or f"user{counter['n']}-{uuid.uuid4().hex[:8]}@example.com"
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": VALID_PASSWORD,
                "full_name": f"User {counter['n']}",
                "workspace_name": workspace_name if owner is None else None,
            },
        )
        assert response.status_code == 201, response.text
        token = response.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        if owner is None:
            workspaces = client.get("/api/v1/workspaces", headers=headers).json()
            workspace_id = workspaces[0]["id"]
        else:
            workspace_id = owner.workspace_id
            if role is not None:
                invite = client.post(
                    owner.url("/members"),
                    headers=owner.headers,
                    json={
                        "email": email,
                        "role": role.value if hasattr(role, "value") else role,
                    },
                )
                assert invite.status_code == 201, invite.text
        me = client.get("/api/v1/auth/me", headers=headers).json()
        return Tenant(
            {
                "headers": headers,
                "workspace_id": workspace_id,
                "user_id": me["user"]["id"],
                "email": email,
                "access_token": token,
            }
        )

    return _make


@pytest.fixture()
def owner(make_tenant) -> Tenant:
    return make_tenant(workspace_name="Acme")


@pytest.fixture()
def create_service(client: TestClient):
    def _create(tenant: Tenant, name: str = "checkout-api", **overrides) -> dict:
        payload = {
            "name": name,
            "environment": "production",
            "description": "Payments service",
            "owner_team": "platform",
            **overrides,
        }
        response = client.post(tenant.url("/services"), headers=tenant.headers, json=payload)
        assert response.status_code == 201, response.text
        return response.json()

    return _create
