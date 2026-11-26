"""Shared schema helpers: UTC serialization, cursor pages, error envelope."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, PlainSerializer


def _serialize_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        value = value.astimezone(UTC).replace(tzinfo=None)
    return value.replace(microsecond=0).isoformat() + "Z"


UtcDateTime = Annotated[datetime, PlainSerializer(_serialize_dt, return_type=str | None)]


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


T = TypeVar("T")


class CursorPage(APIModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False


class Message(APIModel):
    message: str


class ErrorBody(APIModel):
    code: str
    message: str
    details: object | None = None
    request_id: str | None = None


class ErrorEnvelope(APIModel):
    error: ErrorBody


class HealthResponse(APIModel):
    status: str
    database: str
    redis: str
    version: str


__all__ = [
    "APIModel",
    "UtcDateTime",
    "CursorPage",
    "Message",
    "ErrorBody",
    "ErrorEnvelope",
    "HealthResponse",
]
