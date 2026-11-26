"""Auth routes: register, login, refresh, profile."""

from __future__ import annotations

import re
import uuid

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.api.deps import auth_rate_limit, get_current_user
from app.core.config import settings
from app.core.db import get_db
from app.core.errors import Conflict, PermissionDenied, Unauthenticated
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.base import utcnow
from app.models.identity import Membership, Role, User, Workspace
from app.schemas.auth import (
    LoginRequest,
    MembershipSummary,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserOut,
)
from app.services.audit import record_audit

router = APIRouter(prefix="/auth", tags=["auth"])


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:50]
    return slug or "workspace"


def _unique_slug(db: Session, base: str) -> str:
    slug = base
    suffix = 1
    while db.query(Workspace.id).filter(Workspace.slug == slug).first() is not None:
        suffix += 1
        slug = f"{base[:40]}-{suffix}"
    return slug


def _token_pair(user: User) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post("/register", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    email = payload.email.lower().strip()
    auth_rate_limit(request, email)
    if db.query(User.id).filter(User.email == email).first() is not None:
        raise Conflict("an account with this email already exists")

    user = User(
        email=email,
        full_name=payload.full_name.strip()[:200],
        password_hash=hash_password(payload.password),
        is_active=True,
    )
    db.add(user)
    db.flush()

    if payload.workspace_name:
        workspace = Workspace(
            name=payload.workspace_name.strip()[:200],
            slug=_unique_slug(db, _slugify(payload.workspace_name)),
            created_by_id=user.id,
        )
        db.add(workspace)
        db.flush()
        db.add(
            Membership(
                workspace_id=workspace.id,
                user_id=user.id,
                role=Role.OWNER,
                accepted_at=utcnow(),
            )
        )

    record_audit(
        db,
        action="auth.register",
        workspace_id=None,
        actor_id=user.id,
        actor_email=user.email,
        target_type="user",
        target_id=user.id,
        metadata={"created_workspace": bool(payload.workspace_name)},
    )
    db.commit()
    return _token_pair(user)


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)) -> TokenPair:
    email = payload.email.lower().strip()
    auth_rate_limit(request, email)
    user = db.query(User).filter(User.email == email).first()
    if user is None or not user.is_active or not verify_password(payload.password, user.password_hash):
        record_audit(
            db,
            action="auth.login",
            workspace_id=None,
            actor_id=user.id if user else None,
            actor_email=email,
            target_type="user",
            target_id=user.id if user else "",
            outcome="failure",
            metadata={"reason": "invalid_credentials"},
        )
        db.commit()
        raise Unauthenticated("email or password is incorrect")
    user.last_login_at = utcnow()
    record_audit(
        db,
        action="auth.login",
        workspace_id=None,
        actor_id=user.id,
        actor_email=user.email,
        target_type="user",
        target_id=user.id,
    )
    db.commit()
    return _token_pair(user)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenPair:
    try:
        user_id: uuid.UUID = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise Unauthenticated(str(exc)) from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise Unauthenticated("account is not active")
    return _token_pair(user)


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> MeResponse:
    rows = (
        db.query(Membership, Workspace)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .filter(Membership.user_id == user.id)
        .order_by(Workspace.name.asc())
        .all()
    )
    return MeResponse(
        user=UserOut.model_validate(user),
        memberships=[
            MembershipSummary(
                workspace_id=workspace.id,
                workspace_name=workspace.name,
                workspace_slug=workspace.slug,
                role=membership.role.value,
            )
            for membership, workspace in rows
        ],
    )


@router.get("/sessions", response_model=list[MembershipSummary])
def sessions(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> list[MembershipSummary]:
    if user.is_active is False:  # pragma: no cover - defensive
        raise PermissionDenied("account is disabled")
    rows = (
        db.query(Membership, Workspace)
        .join(Workspace, Workspace.id == Membership.workspace_id)
        .filter(Membership.user_id == user.id)
        .all()
    )
    return [
        MembershipSummary(
            workspace_id=workspace.id,
            workspace_name=workspace.name,
            workspace_slug=workspace.slug,
            role=membership.role.value,
        )
        for membership, workspace in rows
    ]


__all__ = ["router"]
