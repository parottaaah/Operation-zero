"""Source-control integrations and verified webhook events."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin, enum_column


class IntegrationProvider(str, enum.Enum):
    GITHUB = "github"


class IntegrationStatus(str, enum.Enum):
    PENDING = "pending"
    CONNECTED = "connected"
    ERROR = "error"
    REVOKED = "revoked"


class WebhookStatus(str, enum.Enum):
    RECEIVED = "received"
    VERIFIED = "verified"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"


class Integration(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "integrations"
    __table_args__ = (
        UniqueConstraint("workspace_id", "provider", "external_account_id", name="uq_integration_account"),
        Index("ix_integrations_workspace_provider", "workspace_id", "provider"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[IntegrationProvider] = mapped_column(
        enum_column(IntegrationProvider, "integration_provider"), nullable=False
    )
    status: Mapped[IntegrationStatus] = mapped_column(
        enum_column(IntegrationStatus, "integration_status"),
        nullable=False,
        default=IntegrationStatus.PENDING,
    )
    external_account: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    external_account_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    repository_full_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    repository_id: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    # Encrypted token material. Never logged, never returned by the API.
    secret_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    config: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    connected_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    last_error: Mapped[str] = mapped_column(String(500), default="", nullable=False)


class WebhookEvent(UUIDMixin, Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("provider", "delivery_id", name="uq_webhook_provider_delivery"),
        Index("ix_webhook_workspace_time", "workspace_id", "received_at"),
        Index("ix_webhook_integration_time", "integration_id", "occurred_at"),
        Index("uq_webhook_provider_body_sha256", "provider", "body_sha256", unique=True),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("integrations.id", ondelete="CASCADE"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(40), nullable=False, default="github")
    delivery_id: Mapped[str] = mapped_column(String(120), nullable=False)
    # SHA-256 of the exact signed request body. Delivery ids are supplied by the
    # sender and are not covered by the HMAC, so a captured body can be replayed
    # with a new delivery id. This hash closes that gap. Nullable for legacy rows
    # created before this column existed.
    body_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    action: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    status: Mapped[WebhookStatus] = mapped_column(
        enum_column(WebhookStatus, "webhook_status"), nullable=False, default=WebhookStatus.RECEIVED
    )
    signature_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reject_reason: Mapped[str] = mapped_column(String(240), default="", nullable=False)
    repository_full_name: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    commit_shas: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    pr_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deployment_ref: Mapped[str] = mapped_column(String(200), default="", nullable=False)
    actor_login: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


__all__ = [
    "IntegrationProvider",
    "IntegrationStatus",
    "WebhookStatus",
    "Integration",
    "WebhookEvent",
]
