"""Public webhook ingress with signature verification and replay protection."""

from __future__ import annotations

import hashlib
import json
import logging

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.errors import PayloadTooLarge, Unauthenticated, ValidationFailed
from app.core.rate_limit import check_rate_limit
from app.models.integration import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
    WebhookEvent,
)
from app.services import github

logger = logging.getLogger(__name__)
router = APIRouter(tags=["webhooks"])


@router.post("/webhooks/github", status_code=status.HTTP_202_ACCEPTED)
async def github_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
    x_github_delivery: str | None = Header(default=None, alias="X-GitHub-Delivery"),
) -> JSONResponse:
    client = request.client.host if request.client else "unknown"
    check_rate_limit(f"webhook:{client}", 300, 60)

    raw_body = await request.body()
    if len(raw_body) > settings.max_request_bytes:
        raise PayloadTooLarge("webhook payload too large")
    if not settings.github_webhook_secret:
        raise Unauthenticated("webhook secret is not configured on this deployment")
    if not github.verify_signature(raw_body, x_hub_signature_256):
        # Reject before parsing untrusted content or writing anything.
        logger.warning("rejected GitHub webhook with invalid or missing signature")
        raise Unauthenticated("webhook signature verification failed")
    if not x_github_event or not x_github_delivery:
        raise ValidationFailed("missing GitHub event or delivery headers")

    # Replay protection is workspace-scoped: a delivery id and the exact signed
    # body are each accepted once per workspace. Delivery ids are not covered by
    # the HMAC, so the body fingerprint closes the new-delivery-id replay gap.
    body_sha256 = hashlib.sha256(raw_body).hexdigest()

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationFailed("webhook body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValidationFailed("webhook body must be a JSON object")

    repository_hint = str((payload.get("repository") or {}).get("full_name") or "")
    integrations = (
        db.query(Integration)
        .filter(
            Integration.provider == IntegrationProvider.GITHUB,
            Integration.repository_full_name == repository_hint,
            Integration.status == IntegrationStatus.CONNECTED,
        )
        .all()
    )
    if not integrations:
        logger.info("github webhook ignored (no matching integration)")
        return JSONResponse({"status": "ignored"}, status_code=202)

    # A delivery fans out to every connected workspace. If a workspace has more
    # than one matching integration, only the first receives the event.
    by_workspace: dict[object, Integration] = {}
    for integration in integrations:
        by_workspace.setdefault(integration.workspace_id, integration)

    created: list[WebhookEvent] = []
    duplicates: list[WebhookEvent] = []
    try:
        for integration in by_workspace.values():
            existing = (
                db.query(WebhookEvent)
                .filter(
                    WebhookEvent.workspace_id == integration.workspace_id,
                    WebhookEvent.provider == "github",
                    or_(
                        WebhookEvent.delivery_id == x_github_delivery[:120],
                        WebhookEvent.body_sha256 == body_sha256,
                    ),
                )
                .first()
            )
            if existing is not None:
                duplicates.append(existing)
                continue
            created.append(
                github.store_webhook(
                    db,
                    event_type=x_github_event,
                    delivery_id=x_github_delivery,
                    payload=payload,
                    signature_verified=True,
                    integration=integration,
                    repository_hint=repository_hint,
                    body_sha256=body_sha256,
                )
            )
        db.commit()
    except IntegrityError:
        # Concurrent redelivery: the unique index won. Re-read the workspace
        # rows and report them as duplicates instead of leaking a 500.
        db.rollback()
        created = []
        duplicates = []
        for integration in by_workspace.values():
            existing = (
                db.query(WebhookEvent)
                .filter(
                    WebhookEvent.workspace_id == integration.workspace_id,
                    WebhookEvent.provider == "github",
                    or_(
                        WebhookEvent.delivery_id == x_github_delivery[:120],
                        WebhookEvent.body_sha256 == body_sha256,
                    ),
                )
                .first()
            )
            if existing is not None:
                duplicates.append(existing)

    created_ids = [str(event.id) for event in created]
    duplicate_ids = [str(event.id) for event in duplicates]
    if not created_ids:
        status_value = "duplicate"
    elif duplicate_ids:
        status_value = "partial"
    else:
        status_value = "verified"
    return JSONResponse(
        {
            "status": status_value,
            "event_id": (created_ids or duplicate_ids or [None])[0],
            "event_ids": created_ids,
            "duplicate_event_ids": duplicate_ids,
        },
        status_code=202,
    )


__all__ = ["router"]
