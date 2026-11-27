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
    WebhookStatus,
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

    # Replay protection: a GitHub delivery id is accepted exactly once. Delivery
    # ids are not covered by the HMAC, so also fingerprint the exact signed body
    # and reject a captured body that arrives under a new delivery id.
    body_sha256 = hashlib.sha256(raw_body).hexdigest()
    duplicate = (
        db.query(WebhookEvent)
        .filter(
            WebhookEvent.provider == "github",
            or_(
                WebhookEvent.delivery_id == x_github_delivery[:120],
                WebhookEvent.body_sha256 == body_sha256,
            ),
        )
        .first()
    )
    if duplicate is not None:
        return JSONResponse({"status": "duplicate", "event_id": str(duplicate.id)}, status_code=202)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationFailed("webhook body is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValidationFailed("webhook body must be a JSON object")

    repository_hint = str((payload.get("repository") or {}).get("full_name") or "")
    integration = (
        db.query(Integration)
        .filter(
            Integration.provider == IntegrationProvider.GITHUB,
            Integration.repository_full_name == repository_hint,
            Integration.status == IntegrationStatus.CONNECTED,
        )
        .first()
    )
    if integration is None:
        logger.info("github webhook ignored (no matching integration)")
        return JSONResponse({"status": "ignored"}, status_code=202)

    try:
        event = github.store_webhook(
            db,
            event_type=x_github_event,
            delivery_id=x_github_delivery,
            payload=payload,
            signature_verified=True,
            integration=integration,
            repository_hint=repository_hint,
            body_sha256=body_sha256,
        )
        db.commit()
    except IntegrityError:
        # Concurrent redelivery: the unique index won, so return the stored row.
        db.rollback()
        existing = (
            db.query(WebhookEvent)
            .filter(
                WebhookEvent.provider == "github",
                or_(
                    WebhookEvent.delivery_id == x_github_delivery[:120],
                    WebhookEvent.body_sha256 == body_sha256,
                ),
            )
            .first()
        )
        if existing is not None:
            return JSONResponse({"status": "duplicate", "event_id": str(existing.id)}, status_code=202)
        raise
    if event.status is not WebhookStatus.VERIFIED:  # pragma: no cover - defensive
        return JSONResponse({"status": event.status.value}, status_code=202)
    return JSONResponse(
        {"status": "verified", "event_id": str(event.id), "duplicate": False},
        status_code=202,
    )


__all__ = ["router"]
