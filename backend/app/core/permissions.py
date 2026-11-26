"""Server-side RBAC.

Permissions are granted to roles; roles come from a workspace membership row that
is loaded on every request. The client never supplies its own role or permissions.
"""

from __future__ import annotations

import enum

from app.core.errors import PermissionDenied
from app.models.identity import ROLE_RANK, Role


class Permission(str, enum.Enum):
    WORKSPACE_READ = "workspace:read"
    WORKSPACE_UPDATE = "workspace:update"
    WORKSPACE_DELETE = "workspace:delete"
    MEMBERS_READ = "members:read"
    MEMBERS_MANAGE = "members:manage"
    MEMBERS_MANAGE_OWNER = "members:manage_owner"
    SERVICES_READ = "services:read"
    SERVICES_WRITE = "services:write"
    TELEMETRY_READ_RAW = "telemetry:read_raw"
    ALERTS_READ = "alerts:read"
    ALERTS_WRITE = "alerts:write"
    INCIDENTS_READ = "incidents:read"
    INCIDENTS_WRITE = "incidents:write"
    INTEGRATIONS_READ = "integrations:read"
    INTEGRATIONS_WRITE = "integrations:write"
    AI_RUN = "ai:run"
    AUDIT_READ = "audit:read"
    REPORTS_EXPORT = "reports:export"


_READ_ONLY = {
    Permission.WORKSPACE_READ,
    Permission.MEMBERS_READ,
    Permission.SERVICES_READ,
    Permission.ALERTS_READ,
    Permission.INCIDENTS_READ,
    Permission.INTEGRATIONS_READ,
    Permission.REPORTS_EXPORT,
}

ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.VIEWER: set(_READ_ONLY),
    Role.SECURITY_ANALYST: _READ_ONLY
    | {
        Permission.TELEMETRY_READ_RAW,
        Permission.ALERTS_WRITE,
        Permission.INCIDENTS_WRITE,
        Permission.AUDIT_READ,
    },
    Role.ENGINEER: _READ_ONLY
    | {
        Permission.TELEMETRY_READ_RAW,
        Permission.SERVICES_WRITE,
        Permission.ALERTS_WRITE,
        Permission.INCIDENTS_WRITE,
        Permission.AI_RUN,
    },
    Role.ADMIN: _READ_ONLY
    | {
        Permission.WORKSPACE_UPDATE,
        Permission.MEMBERS_MANAGE,
        Permission.TELEMETRY_READ_RAW,
        Permission.SERVICES_WRITE,
        Permission.ALERTS_WRITE,
        Permission.INCIDENTS_WRITE,
        Permission.INTEGRATIONS_WRITE,
        Permission.AI_RUN,
        Permission.AUDIT_READ,
    },
    Role.OWNER: set(Permission) | {Permission.MEMBERS_MANAGE_OWNER},
}


def role_has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


def require_permission(role: Role, permission: Permission) -> None:
    if not role_has_permission(role, permission):
        raise PermissionDenied(f"role '{role.value}' cannot perform '{permission.value}'")


def can_manage_role(actor: Role, target: Role) -> bool:
    """Admins may manage every role except owner; only owners manage owners."""
    if actor is Role.OWNER:
        return True
    if actor is Role.ADMIN:
        return target is not Role.OWNER
    return False


def outranks(actor: Role, target: Role) -> bool:
    return ROLE_RANK[actor] > ROLE_RANK[target]


__all__ = [
    "Permission",
    "ROLE_PERMISSIONS",
    "role_has_permission",
    "require_permission",
    "can_manage_role",
    "outranks",
]
