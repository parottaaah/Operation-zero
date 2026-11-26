"""Structured log ingestion and query schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.models.telemetry import Severity
from app.schemas.common import APIModel, UtcDateTime

MAX_ATTRIBUTES_BYTES = 16_384
MAX_ATTRIBUTE_KEYS = 60
MAX_DEPTH = 4


def _check_depth(value: Any, depth: int = 0) -> None:
    if depth > MAX_DEPTH:
        raise ValueError("attributes are nested too deeply")
    if isinstance(value, dict):
        if len(value) > MAX_ATTRIBUTE_KEYS:
            raise ValueError("too many attribute keys")
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 100:
                raise ValueError("attribute keys must be strings under 100 characters")
            _check_depth(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > MAX_ATTRIBUTE_KEYS:
            raise ValueError("too many attribute list items")
        for item in value:
            _check_depth(item, depth + 1)


class LogEventIn(APIModel):
    message: str = Field(min_length=1, max_length=8000)
    severity: Severity = Severity.INFO
    timestamp: datetime | None = None
    environment: str | None = Field(default=None, max_length=40)
    attributes: dict[str, Any] = Field(default_factory=dict)
    trace_id: str | None = Field(default=None, max_length=64)
    request_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=128)

    @field_validator("attributes")
    @classmethod
    def attributes_bounded(cls, value: dict[str, Any]) -> dict[str, Any]:
        _check_depth(value)
        import json

        if len(json.dumps(value, default=str)) > MAX_ATTRIBUTES_BYTES:
            raise ValueError("attributes exceed the 16 KiB limit")
        return value

    @field_validator("timestamp")
    @classmethod
    def timestamp_plausible(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        from datetime import UTC, timedelta

        if value.tzinfo is not None:
            value = value.astimezone(UTC).replace(tzinfo=None)
        from app.models.base import utcnow

        now = utcnow()
        if value > now + timedelta(minutes=5):
            raise ValueError("event timestamp is in the future")
        if value < now - timedelta(days=30):
            raise ValueError("event timestamp is older than the 30-day ingestion limit")
        return value


class LogBatchIn(APIModel):
    events: list[LogEventIn] = Field(min_length=1)

    @model_validator(mode="after")
    def batch_size(self) -> LogBatchIn:
        from app.core.config import settings

        if len(self.events) > settings.max_log_batch_events:
            raise ValueError(f"batch exceeds {settings.max_log_batch_events} events")
        return self


class LogIngestResult(APIModel):
    accepted: int
    duplicates: int
    redactions: int
    event_ids: list[uuid.UUID]


class LogEventOut(APIModel):
    id: uuid.UUID
    service_id: uuid.UUID | None
    service_name: str | None = None
    environment: str
    severity: Severity
    message: str
    event_timestamp: UtcDateTime
    received_at: UtcDateTime
    attributes: dict
    redaction_count: int
    redacted_fields: list[str]
    trace_id: str | None
    request_id: str | None


class LogQuery(APIModel):
    service_id: uuid.UUID | None = None
    environment: str | None = None
    severity: Severity | None = None
    q: str | None = Field(default=None, max_length=200)
    from_ts: datetime | None = None
    to_ts: datetime | None = None
    limit: int = Field(default=50, ge=1, le=200)
    cursor: str | None = None


__all__ = [
    "LogEventIn",
    "LogBatchIn",
    "LogIngestResult",
    "LogEventOut",
    "LogQuery",
]
