"""GitHub OAuth connection, integration management and deployment context."""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.api.deps import WorkspaceContext, require
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import NotFound, ServiceUnavailable, ValidationFailed
from app.core.permissions import Permission
from app.core.security import decrypt_secret
from app.models.identity import User
from app.models.integration import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
    WebhookEvent,
)
from app.schemas.common import CursorPage, Message
from app.schemas.integrations import (
    DeploymentContextOut,
    GitHubConnectOut,
    GitHubConnectRequest,
    IntegrationOut,
    WebhookEventOut,
)
from app.services import github

logger = logging.getLogger(__name__)
router = APIRouter(tags=["integrations"])


def _integration_out(integration: Integration) -> IntegrationOut:
    return IntegrationOut.model_validate(integration)


@router.get("/workspaces/{workspace_id}/integrations", response_model=list[IntegrationOut])
def list_integrations(
    context: WorkspaceContext = Depends(require(Permission.INTEGRATIONS_READ)),
    db: Session = Depends(get_db),
) -> list[IntegrationOut]:
    rows = (
        db.query(Integration)
        .filter(Integration.workspace_id == context.workspace_id)
        .order_by(Integration.created_at.desc())
        .all()
    )
    return [_integration_out(row) for row in rows]


@router.post(
    "/workspaces/{workspace_id}/integrations/github/connect",
    response_model=GitHubConnectOut,
    status_code=status.HTTP_201_CREATED,
)
def connect_github(
    payload: GitHubConnectRequest,
    context: WorkspaceContext = Depends(require(Permission.INTEGRATIONS_WRITE)),
    db: Session = Depends(get_db),
) -> GitHubConnectOut:
    integration, authorize_url = github.start_oauth(
        db,
        workspace_id=context.workspace_id,
        actor=context.user,
        repository=payload.repository_full_name,
    )
    db.commit()
    return GitHubConnectOut(
        integration_id=integration.id,
        authorize_url=authorize_url,
        scopes=integration.scopes,
        data_processing_notice=(
            "OPERATION ZERO reads repository metadata (commits, pull requests, deployments) "
            "only. It never writes to your repository and never stores source code. "
            "Tokens are encrypted at rest and are revoked when you disconnect."
        ),
    )


@router.get("/integrations/github/callback")
async def github_callback(
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    target = f"{settings.public_web_url.rstrip('/')}/integrations"
    if error or not code or not state:
        return RedirectResponse(f"{target}?status=error&reason=denied")
    try:
        token_body = await github.exchange_code(code, state)
        account = await github.fetch_account(token_body["access_token"])
        from app.models.platform import IdempotencyKey

        record = (
            db.query(IdempotencyKey)
            .filter(IdempotencyKey.scope == github.OAUTH_STATE_SCOPE, IdempotencyKey.key == state)
            .first()
        )
        if record is None:
            raise ValidationFailed("OAuth state is unknown or expired")
        integration = db.get(Integration, uuid.UUID(record.response_body["integration_id"]))
        repository = None
        if integration is not None and integration.config.get("requested_repository"):
            repository = await github.fetch_repository(
                token_body["access_token"], integration.config["requested_repository"]
            )
        github.complete_oauth(
            db,
            code=code,
            state=state,
            token_body=token_body,
            account=account,
            repository=repository,
            actor_email=account.get("login", ""),
        )
        db.commit()
        return RedirectResponse(f"{target}?status=connected")
    except Exception as exc:
        logger.warning("github oauth callback failed: %s", type(exc).__name__)
        db.rollback()
        return RedirectResponse(f"{target}?status=error&reason=oauth_failed")


@router.post("/workspaces/{workspace_id}/integrations/{integration_id}/test", response_model=dict)
async def test_integration(
    integration_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.INTEGRATIONS_WRITE)),
    db: Session = Depends(get_db),
) -> dict:
    integration = github.integration_for_workspace(db, context.workspace_id, integration_id)
    if integration.status is not IntegrationStatus.CONNECTED or not integration.secret_encrypted:
        raise ServiceUnavailable("integration is not connected")
    github.ensure_configured()
    try:
        token = decrypt_secret(integration.secret_encrypted)
        account = await github.fetch_account(token)
        integration.last_error = ""
        db.commit()
        return {
            "ok": True,
            "account": account.get("login"),
            "scopes": integration.scopes,
            "repository": integration.repository_full_name,
        }
    except Exception as exc:
        integration.last_error = type(exc).__name__
        integration.status = IntegrationStatus.ERROR
        db.commit()
        return {"ok": False, "error": type(exc).__name__}


@router.delete("/workspaces/{workspace_id}/integrations/{integration_id}", response_model=Message)
def disconnect_integration(
    integration_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.INTEGRATIONS_WRITE)),
    db: Session = Depends(get_db),
) -> Message:
    integration = github.integration_for_workspace(db, context.workspace_id, integration_id)
    github.revoke_integration(db, integration, actor=context.user, request_id=context.request_id)
    db.commit()
    return Message(message="integration revoked")


@router.get("/workspaces/{workspace_id}/deployments", response_model=DeploymentContextOut)
def deployment_context(
    repository: str | None = Query(default=None, max_length=200),
    event_type: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=50, ge=1, le=200),
    context: WorkspaceContext = Depends(require(Permission.SERVICES_READ)),
    db: Session = Depends(get_db),
) -> DeploymentContextOut:
    query = db.query(WebhookEvent).filter(
        WebhookEvent.workspace_id == context.workspace_id,
        WebhookEvent.signature_verified.is_(True),
    )
    if repository:
        query = query.filter(WebhookEvent.repository_full_name == repository)
    if event_type:
        query = query.filter(WebhookEvent.event_type == event_type)
    events = query.order_by(WebhookEvent.occurred_at.desc()).limit(limit).all()
    integrations = (
        db.query(Integration)
        .filter(
            Integration.workspace_id == context.workspace_id,
            Integration.provider == IntegrationProvider.GITHUB,
        )
        .order_by(Integration.created_at.desc())
        .all()
    )
    return DeploymentContextOut(
        events=[WebhookEventOut.model_validate(event) for event in events],
        integrations=[_integration_out(integration) for integration in integrations],
    )


@router.get("/workspaces/{workspace_id}/deployment-events", response_model=CursorPage[WebhookEventOut])
def list_deployment_events(
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    context: WorkspaceContext = Depends(require(Permission.SERVICES_READ)),
    db: Session = Depends(get_db),
) -> CursorPage[WebhookEventOut]:
    from app.core.pagination import paginate

    rows, next_cursor = paginate(
        db,
        WebhookEvent,
        filters=[WebhookEvent.workspace_id == context.workspace_id],
        order_column=WebhookEvent.received_at,
        limit=limit,
        cursor=cursor,
    )
    return CursorPage(
        items=[WebhookEventOut.model_validate(row) for row in rows],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.get("/workspaces/{workspace_id}/integrations/github/webhook-config", response_model=dict)
def webhook_config(
    context: WorkspaceContext = Depends(require(Permission.INTEGRATIONS_READ)),
) -> dict:
    return {
        "webhook_url": f"{settings.api_base_url.rstrip('/')}/api/v1/webhooks/github",
        "content_type": "application/json",
        "events": ["push", "pull_request", "deployment", "deployment_status"],
        "secret_configured": bool(settings.github_webhook_secret),
    }


__all__ = ["router", "NotFound", "User", "Request"]
