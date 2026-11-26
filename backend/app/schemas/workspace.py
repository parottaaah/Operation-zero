"""Workspace, membership and audit schemas."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import EmailStr, Field, field_validator

from app.models.identity import Role
from app.schemas.common import APIModel, UtcDateTime


class WorkspaceCreate(APIModel):
    name: str = Field(min_length=2, max_length=200)
    timezone: str = Field(default="UTC", max_length=64)


class WorkspaceUpdate(APIModel):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    timezone: str | None = Field(default=None, max_length=64)
    telemetry_retention_days: int | None = Field(default=None, ge=1, le=365)
    audit_retention_days: int | None = Field(default=None, ge=30, le=3650)
    ai_retention_days: int | None = Field(default=None, ge=1, le=365)
    ai_data_processing_acknowledged: bool | None = None


class WorkspaceOut(APIModel):
    id: uuid.UUID
    name: str
    slug: str
    timezone: str
    telemetry_retention_days: int
    audit_retention_days: int
    ai_retention_days: int
    ai_data_processing_acknowledged: bool
    role: str | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class MemberOut(APIModel):
    user_id: uuid.UUID
    email: str
    full_name: str
    role: Role
    accepted_at: UtcDateTime | None = None
    created_at: UtcDateTime


class MemberInvite(APIModel):
    email: EmailStr
    role: Role = Role.VIEWER


class MemberRoleUpdate(APIModel):
    role: Role

    @field_validator("role")
    @classmethod
    def not_owner_implicitly(cls, value: Role) -> Role:
        return value


class AuditEventOut(APIModel):
    id: uuid.UUID
    workspace_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    actor_email: str
    action: str
    target_type: str
    target_id: str
    outcome: str
    request_id: str
    metadata_json: dict
    created_at: UtcDateTime


class AuditQuery(APIModel):
    action: str | None = None
    actor_id: uuid.UUID | None = None
    target_type: str | None = None
    from_ts: UtcDateTime | None = None
    to_ts: UtcDateTime | None = None
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None


ReportFormat = Literal["md", "pdf"]

__all__ = [
    "WorkspaceCreate",
    "WorkspaceUpdate",
    "WorkspaceOut",
    "MemberOut",
    "MemberInvite",
    "MemberRoleUpdate",
    "AuditEventOut",
    "AuditQuery",
    "ReportFormat",
]
