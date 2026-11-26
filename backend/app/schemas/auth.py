"""Authentication and profile schemas."""

from __future__ import annotations

import uuid

from pydantic import EmailStr, Field, field_validator

from app.schemas.common import APIModel, UtcDateTime


class RegisterRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=200)
    full_name: str = Field(default="", max_length=200)
    workspace_name: str | None = Field(default=None, max_length=200)

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if value.lower() in {"password1234", "changeme1234", "qwertyuiop12"}:
            raise ValueError("password is too common")
        if not any(c.isdigit() for c in value) or not any(c.isalpha() for c in value):
            raise ValueError("password must contain letters and numbers")
        return value


class LoginRequest(APIModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class RefreshRequest(APIModel):
    refresh_token: str


class TokenPair(APIModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(APIModel):
    id: uuid.UUID
    email: str
    full_name: str
    is_active: bool
    is_platform_admin: bool
    last_login_at: UtcDateTime | None = None
    created_at: UtcDateTime


class MembershipSummary(APIModel):
    workspace_id: uuid.UUID
    workspace_name: str
    workspace_slug: str
    role: str


class MeResponse(APIModel):
    user: UserOut
    memberships: list[MembershipSummary]


__all__ = [
    "RegisterRequest",
    "LoginRequest",
    "RefreshRequest",
    "TokenPair",
    "UserOut",
    "MembershipSummary",
    "MeResponse",
]
