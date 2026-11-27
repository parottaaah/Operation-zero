"""GitHub integration: least-privilege OAuth, repository binding, webhooks.

Tokens are encrypted at rest and never returned through the API. Webhook requests
are verified with HMAC-SHA256 over the raw body, deduplicated by delivery id, and
stored as bounded, sanitized context — never executed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
import uuid
from datetime import timedelta

import httpx
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import Conflict, NotFound, ServiceUnavailable, ValidationFailed
from app.models.base import utcnow
from app.models.identity import User
from app.models.integration import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
    WebhookEvent,
    WebhookStatus,
)
from app.models.platform import IdempotencyKey
from app.services.audit import record_audit

logger = logging.getLogger(__name__)

OAUTH_STATE_SCOPE = "github_oauth_state"
OAUTH_STATE_TTL_MINUTES = 10
MAX_PAYLOAD_CHARS = 60_000


def ensure_configured() -> None:
    if not settings.github_client_id or not settings.github_client_secret:
        raise ServiceUnavailable(
            "GitHub integration is not configured on this deployment",
            details={"required": ["OZ_GITHUB_CLIENT_ID", "OZ_GITHUB_CLIENT_SECRET"]},
        )


def start_oauth(
    session: Session, *, workspace_id: uuid.UUID, actor: User, repository: str = ""
) -> tuple[Integration, str]:
    ensure_configured()
    state = secrets.token_urlsafe(32)
    integration = Integration(
        workspace_id=workspace_id,
        provider=IntegrationProvider.GITHUB,
        status=IntegrationStatus.PENDING,
        repository_full_name=repository.strip()[:200],
        scopes=[s for s in re.split(r"[,\s]+", settings.github_oauth_scopes) if s],
        config={"oauth_state": state, "requested_repository": repository.strip()[:200]},
        connected_by_id=actor.id,
    )
    session.add(integration)
    session.flush()
    session.add(
        IdempotencyKey(
            scope=OAUTH_STATE_SCOPE,
            key=state,
            response_body={
                "workspace_id": str(workspace_id),
                "integration_id": str(integration.id),
                "user_id": str(actor.id),
            },
            created_at=utcnow(),
            expires_at=utcnow() + timedelta(minutes=OAUTH_STATE_TTL_MINUTES),
        )
    )
    record_audit(
        session,
        action="integration.github.connect_started",
        workspace_id=workspace_id,
        actor_id=actor.id,
        actor_email=actor.email,
        target_type="integration",
        target_id=integration.id,
        metadata={"scopes": integration.scopes, "repository": integration.repository_full_name},
    )
    redirect_uri = f"{settings.api_base_url.rstrip('/')}/api/v1/integrations/github/callback"
    scopes = "+".join(integration.scopes) or "read:user"
    authorize_url = (
        f"{settings.github_oauth_authorize_url}?client_id={settings.github_client_id}"
        f"&redirect_uri={redirect_uri}&scope={scopes}&state={state}"
    )
    return integration, authorize_url


async def exchange_code(code: str, state: str, *, client: httpx.AsyncClient | None = None) -> dict:
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        response = await client.post(
            settings.github_oauth_token_url,
            headers={"Accept": "application/json"},
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "state": state,
            },
        )
        response.raise_for_status()
        body = response.json()
    finally:
        if own:
            await client.aclose()
    if "access_token" not in body:
        raise ValidationFailed("GitHub did not return an access token")
    return body


async def fetch_account(token: str, *, client: httpx.AsyncClient | None = None) -> dict:
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        response = await client.get(
            f"{settings.github_api_url}/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        response.raise_for_status()
        return response.json()
    finally:
        if own:
            await client.aclose()


async def fetch_repository(token: str, full_name: str, *, client=None) -> dict | None:
    own = client is None
    client = client or httpx.AsyncClient(timeout=15)
    try:
        response = await client.get(
            f"{settings.github_api_url}/repos/{full_name}",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
        )
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    finally:
        if own:
            await client.aclose()


def complete_oauth(
    session: Session,
    *,
    code: str,
    state: str,
    token_body: dict,
    account: dict,
    repository: dict | None,
    actor_email: str,
) -> Integration:
    from app.core.security import encrypt_secret

    record = (
        session.query(IdempotencyKey)
        .filter(IdempotencyKey.scope == OAUTH_STATE_SCOPE, IdempotencyKey.key == state)
        .first()
    )
    if record is None or record.expires_at < utcnow():
        raise ValidationFailed("OAuth state is invalid or has expired")
    integration_id = uuid.UUID(record.response_body["integration_id"])
    integration = session.get(Integration, integration_id)
    if integration is None or integration.status is not IntegrationStatus.PENDING:
        raise Conflict("integration is not awaiting authorization")
    if integration.config.get("oauth_state") != state:
        raise ValidationFailed("OAuth state does not match this integration")

    token = token_body["access_token"]
    integration.secret_encrypted = encrypt_secret(token)
    integration.external_account = (account.get("login") or "")[:200]
    integration.external_account_id = str(account.get("id") or "")[:120]
    integration.status = IntegrationStatus.CONNECTED
    integration.connected_at = utcnow()
    if repository:
        integration.repository_full_name = repository.get("full_name", "")[:200]
        integration.repository_id = str(repository.get("id") or "")[:120]
        integration.config = {
            **{k: v for k, v in integration.config.items() if k != "oauth_state"},
            "default_branch": repository.get("default_branch", "main"),
            "private": bool(repository.get("private")),
            "webhook_url": f"{settings.api_base_url.rstrip('/')}/api/v1/webhooks/github",
        }
    else:
        integration.config = {k: v for k, v in integration.config.items() if k != "oauth_state"}
    session.delete(record)
    record_audit(
        session,
        action="integration.github.connected",
        workspace_id=integration.workspace_id,
        actor_id=integration.connected_by_id,
        actor_email=actor_email,
        target_type="integration",
        target_id=integration.id,
        metadata={
            "account": integration.external_account,
            "repository": integration.repository_full_name,
            "scopes": integration.scopes,
        },
    )
    return integration


def revoke_integration(
    session: Session, integration: Integration, *, actor: User, request_id: str = ""
) -> None:
    integration.status = IntegrationStatus.REVOKED
    integration.revoked_at = utcnow()
    integration.secret_encrypted = ""
    record_audit(
        session,
        action="integration.revoked",
        workspace_id=integration.workspace_id,
        actor_id=actor.id,
        actor_email=actor.email,
        target_type="integration",
        target_id=integration.id,
        request_id=request_id,
    )


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not settings.github_webhook_secret:
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = (
        "sha256=" + hmac.new(settings.github_webhook_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    )
    return hmac.compare_digest(expected, signature_header)


def _ts(value: str | None):
    if not value:
        return None
    from datetime import datetime

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _sanitize_payload(payload: dict) -> dict:
    raw = json.dumps(payload, default=str)
    if len(raw) > MAX_PAYLOAD_CHARS:
        payload = {"_truncated": True, "_original_bytes": len(raw)}
    return payload


def parse_webhook(*, event_type: str, delivery_id: str, payload: dict, signature_verified: bool) -> dict:
    repository = payload.get("repository") or {}
    result = {
        "event_type": event_type[:80],
        "action": str(payload.get("action") or "")[:80],
        "repository_full_name": str(repository.get("full_name") or "")[:200],
        "commit_shas": [],
        "pr_number": None,
        "deployment_ref": "",
        "actor_login": str((payload.get("sender") or {}).get("login") or "")[:120],
        "occurred_at": None,
        "payload": _sanitize_payload(payload),
        "signature_verified": signature_verified,
        "delivery_id": delivery_id,
    }
    if event_type == "push":
        shas = [payload.get("after")] if payload.get("after") else []
        shas += [c.get("id") for c in payload.get("commits", []) if c.get("id")]
        result["commit_shas"] = list(dict.fromkeys(s for s in shas if s))[:10]
        result["occurred_at"] = _ts(payload.get("head_commit", {}).get("timestamp"))
        result["deployment_ref"] = str(payload.get("ref") or "")[:200]
    elif event_type == "pull_request":
        pr = payload.get("pull_request") or {}
        result["pr_number"] = pr.get("number")
        result["commit_shas"] = [s for s in [pr.get("head", {}).get("sha"), pr.get("merge_commit_sha")] if s][
            :5
        ]
        result["occurred_at"] = _ts(pr.get("updated_at"))
        result["deployment_ref"] = str(pr.get("html_url") or "")[:200]
    elif event_type == "deployment":
        deployment = payload.get("deployment") or {}
        result["commit_shas"] = [s for s in [deployment.get("sha")] if s][:5]
        result["occurred_at"] = _ts(deployment.get("created_at"))
        result["deployment_ref"] = str(deployment.get("ref") or "")[:200]
    elif event_type == "deployment_status":
        deployment = payload.get("deployment") or {}
        status = payload.get("deployment_status") or {}
        result["commit_shas"] = [s for s in [deployment.get("sha")] if s][:5]
        result["occurred_at"] = _ts(status.get("created_at"))
        result["deployment_ref"] = str(status.get("environment") or deployment.get("ref") or "")[:200]
    return result


def store_webhook(
    session: Session,
    *,
    event_type: str,
    delivery_id: str,
    payload: dict,
    signature_verified: bool,
    integration: Integration | None,
    repository_hint: str = "",
    body_sha256: str | None = None,
) -> WebhookEvent:
    workspace_id = integration.workspace_id if integration is not None else None
    delivery_filters = [WebhookEvent.provider == "github", WebhookEvent.delivery_id == delivery_id]
    if workspace_id is not None:
        delivery_filters.append(WebhookEvent.workspace_id == workspace_id)
    existing = session.query(WebhookEvent).filter(*delivery_filters).first()
    if existing is not None:
        return existing
    if body_sha256:
        body_filters = [WebhookEvent.provider == "github", WebhookEvent.body_sha256 == body_sha256]
        if workspace_id is not None:
            body_filters.append(WebhookEvent.workspace_id == workspace_id)
        existing_body = session.query(WebhookEvent).filter(*body_filters).first()
        if existing_body is not None:
            return existing_body

    parsed = parse_webhook(
        event_type=event_type,
        delivery_id=delivery_id,
        payload=payload,
        signature_verified=signature_verified,
    )
    repository = parsed["repository_full_name"] or repository_hint
    if integration is None and repository:
        integration = (
            session.query(Integration)
            .filter(
                Integration.provider == IntegrationProvider.GITHUB,
                Integration.repository_full_name == repository,
                Integration.status == IntegrationStatus.CONNECTED,
            )
            .first()
        )
    if integration is None:
        raise NotFound("no connected integration matches this repository")

    event = WebhookEvent(
        workspace_id=integration.workspace_id,
        integration_id=integration.id,
        provider="github",
        delivery_id=delivery_id[:120],
        body_sha256=body_sha256,
        event_type=parsed["event_type"],
        action=parsed["action"],
        status=WebhookStatus.VERIFIED if signature_verified else WebhookStatus.REJECTED,
        signature_verified=signature_verified,
        repository_full_name=repository,
        commit_shas=parsed["commit_shas"],
        pr_number=parsed["pr_number"],
        deployment_ref=parsed["deployment_ref"],
        actor_login=parsed["actor_login"],
        occurred_at=parsed["occurred_at"] or utcnow(),
        received_at=utcnow(),
        payload=parsed["payload"],
    )
    session.add(event)
    if signature_verified:
        integration.last_event_at = event.received_at
    session.flush()
    return event


def integration_for_workspace(session: Session, workspace_id, integration_id) -> Integration:
    integration = session.get(Integration, integration_id)
    if integration is None or integration.workspace_id != workspace_id:
        raise NotFound("integration not found")
    return integration


__all__ = [
    "ensure_configured",
    "start_oauth",
    "exchange_code",
    "fetch_account",
    "fetch_repository",
    "complete_oauth",
    "revoke_integration",
    "verify_signature",
    "parse_webhook",
    "store_webhook",
    "integration_for_workspace",
]
