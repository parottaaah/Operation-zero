"""Shared FastAPI dependencies: authentication, tenant context, RBAC, rate limits."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.errors import NotFound, RateLimited, Unauthenticated
from app.core.permissions import Permission, require_permission
from app.core.rate_limit import check_rate_limit
from app.core.security import TokenError, decode_token
from app.models.identity import Membership, Role, User, Workspace

_bearer = HTTPBearer(auto_error=False)


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "") or request.headers.get("X-Request-ID", "")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None or not credentials.credentials:
        raise Unauthenticated("missing bearer token")
    try:
        user_id = decode_token(credentials.credentials, expected_type="access")
    except TokenError as exc:
        raise Unauthenticated(str(exc)) from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise Unauthenticated("account is not active")
    return user


@dataclass
class WorkspaceContext:
    workspace: Workspace
    membership: Membership
    role: Role
    user: User
    request_id: str = ""

    @property
    def workspace_id(self) -> uuid.UUID:
        return self.workspace.id


def get_workspace_context(
    workspace_id: uuid.UUID,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> WorkspaceContext:
    membership = (
        db.query(Membership)
        .filter(Membership.workspace_id == workspace_id, Membership.user_id == user.id)
        .first()
    )
    workspace = db.get(Workspace, workspace_id)
    if membership is None or workspace is None:
        # 404 (not 403) so workspace ids cannot be enumerated by non-members.
        raise NotFound("workspace not found")
    return WorkspaceContext(
        workspace=workspace,
        membership=membership,
        role=membership.role,
        user=user,
        request_id=get_request_id(request),
    )


def require(permission: Permission):
    def dependency(context: WorkspaceContext = Depends(get_workspace_context)) -> WorkspaceContext:
        require_permission(context.role, permission)
        return context

    return dependency


def enforce_rate_limit(key: str, limit: int, window_seconds: int = 60) -> None:
    check_rate_limit(key, limit, window_seconds)


def auth_rate_limit(request: Request, email: str = "") -> None:
    from app.core.config import settings

    client = request.client.host if request.client else "unknown"
    enforce_rate_limit(f"auth:{client}:{email.lower()[:120]}", settings.auth_rate_limit_per_minute, 60)


def ai_rate_limit(context: WorkspaceContext) -> None:
    from app.core.config import settings

    enforce_rate_limit(f"ai:{context.workspace_id}:{context.user.id}", settings.ai_rate_limit_per_minute, 60)


def parse_optional_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes"}


def request_id_header(
    x_request_id: str | None = Header(default=None, alias="X-Request-ID"),
) -> str | None:
    return x_request_id


def utc_from_param(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


__all__ = [
    "WorkspaceContext",
    "get_current_user",
    "get_workspace_context",
    "require",
    "enforce_rate_limit",
    "auth_rate_limit",
    "ai_rate_limit",
    "get_request_id",
    "utc_from_param",
    "RateLimited",
]
