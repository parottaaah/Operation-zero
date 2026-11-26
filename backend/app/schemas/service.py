"""Service registry and health-check schemas."""

from __future__ import annotations

import uuid

from pydantic import Field, field_validator

from app.models.service import Environment, HealthResultStatus, ServiceStatus
from app.schemas.common import APIModel, UtcDateTime


class HealthCheckConfigIn(APIModel):
    url: str = Field(min_length=8, max_length=2048)
    method: str = Field(default="GET", max_length=8)
    expected_status_codes: list[int] = Field(default_factory=lambda: [200], min_length=1, max_length=10)
    interval_seconds: int = Field(default=60, ge=15, le=3600)
    timeout_seconds: int = Field(default=5, ge=1, le=60)
    failure_threshold: int = Field(default=2, ge=1, le=10)
    recovery_threshold: int = Field(default=1, ge=1, le=10)
    enabled: bool = True

    @field_validator("method")
    @classmethod
    def allowed_method(cls, value: str) -> str:
        method = value.upper()
        if method not in {"GET", "HEAD"}:
            raise ValueError("health checks support GET or HEAD only")
        return method

    @field_validator("expected_status_codes")
    @classmethod
    def valid_codes(cls, values: list[int]) -> list[int]:
        if any(code < 100 or code > 599 for code in values):
            raise ValueError("expected status codes must be between 100 and 599")
        return sorted(set(values))


class HealthCheckOut(APIModel):
    id: uuid.UUID
    service_id: uuid.UUID
    url: str
    method: str
    expected_status_codes: list[int]
    interval_seconds: int
    timeout_seconds: int
    failure_threshold: int
    recovery_threshold: int
    enabled: bool
    consecutive_failures: int
    consecutive_successes: int
    last_error: str
    created_at: UtcDateTime
    updated_at: UtcDateTime


class ServiceCreate(APIModel):
    name: str = Field(min_length=1, max_length=160)
    environment: Environment = Environment.PRODUCTION
    description: str = Field(default="", max_length=4000)
    owner_team: str = Field(default="", max_length=120)
    health_check: HealthCheckConfigIn | None = None


class ServiceUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    status: ServiceStatus | None = None
    description: str | None = Field(default=None, max_length=4000)
    owner_team: str | None = Field(default=None, max_length=120)


class ServiceOut(APIModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    slug: str
    environment: Environment
    description: str
    owner_team: str
    status: ServiceStatus
    last_checked_at: UtcDateTime | None = None
    ingestion_key_last4: str
    health_check: HealthCheckOut | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class IngestionKeyOut(APIModel):
    service_id: uuid.UUID
    ingestion_key: str
    ingestion_key_last4: str
    warning: str = "Store this key now; it is shown only once."


class HealthResultOut(APIModel):
    id: uuid.UUID
    service_id: uuid.UUID
    status: HealthResultStatus
    effective_status: ServiceStatus
    status_code: int | None
    latency_ms: float | None
    error_kind: str
    error_message: str
    checked_at: UtcDateTime


class ServiceHealthSummary(APIModel):
    service: ServiceOut
    results: list[HealthResultOut]
    availability: float | None = None
    p95_latency_ms: float | None = None


class RunCheckOut(APIModel):
    result: HealthResultOut
    service_status: ServiceStatus


__all__ = [
    "HealthCheckConfigIn",
    "HealthCheckOut",
    "ServiceCreate",
    "ServiceUpdate",
    "ServiceOut",
    "IngestionKeyOut",
    "HealthResultOut",
    "ServiceHealthSummary",
    "RunCheckOut",
]


class ServiceCreatedOut(ServiceOut):
    ingestion_key: str


__all__ = [*__all__, "ServiceCreatedOut"]
