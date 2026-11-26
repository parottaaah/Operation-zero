"""Integration and deployment-context schemas."""

from __future__ import annotations

import uuid

from pydantic import Field

from app.models.integration import IntegrationProvider, IntegrationStatus
from app.schemas.common import APIModel, UtcDateTime


class GitHubConnectRequest(APIModel):
    repository_full_name: str = Field(default="", max_length=200)


class GitHubConnectOut(APIModel):
    integration_id: uuid.UUID
    authorize_url: str
    scopes: list[str]
    data_processing_notice: str


class IntegrationOut(APIModel):
    id: uuid.UUID
    provider: IntegrationProvider
    status: IntegrationStatus
    external_account: str
    external_account_id: str
    repository_full_name: str
    repository_id: str
    scopes: list[str]
    config: dict
    connected_at: UtcDateTime | None
    revoked_at: UtcDateTime | None
    last_event_at: UtcDateTime | None
    last_error: str
    created_at: UtcDateTime


class WebhookEventOut(APIModel):
    id: uuid.UUID
    provider: str
    event_type: str
    action: str
    status: str
    signature_verified: bool
    repository_full_name: str
    commit_shas: list[str]
    pr_number: int | None
    deployment_ref: str
    actor_login: str
    occurred_at: UtcDateTime | None
    received_at: UtcDateTime


class DeploymentContextOut(APIModel):
    events: list[WebhookEventOut]
    integrations: list[IntegrationOut]


__all__ = [
    "GitHubConnectRequest",
    "GitHubConnectOut",
    "IntegrationOut",
    "WebhookEventOut",
    "DeploymentContextOut",
]
