"""Service registry, health-check configuration and health-check results."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDMixin, enum_column


class Environment(str, enum.Enum):
    PRODUCTION = "production"
    STAGING = "staging"
    DEVELOPMENT = "development"


class ServiceStatus(str, enum.Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    PAUSED = "paused"


class HealthResultStatus(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    ERROR = "error"
    TIMEOUT = "timeout"


class Service(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "services"
    __table_args__ = (
        UniqueConstraint("workspace_id", "name", "environment", name="uq_service_workspace_name_env"),
        Index("ix_services_workspace_status", "workspace_id", "status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), nullable=False)
    environment: Mapped[Environment] = mapped_column(
        enum_column(Environment, "environment"), nullable=False, default=Environment.PRODUCTION
    )
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[ServiceStatus] = mapped_column(
        enum_column(ServiceStatus, "service_status"), nullable=False, default=ServiceStatus.UNKNOWN
    )
    owner_team: Mapped[str] = mapped_column(String(120), default="", nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Hashed ingestion credential. The plaintext key is shown exactly once.
    ingestion_key_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    ingestion_key_last4: Mapped[str] = mapped_column(String(4), default="", nullable=False)
    ingestion_key_rotated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)

    health_check: Mapped[HealthCheck | None] = relationship(
        back_populates="service", uselist=False, cascade="all, delete-orphan"
    )


class HealthCheck(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "health_checks"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    method: Mapped[str] = mapped_column(String(8), default="GET", nullable=False)
    expected_status_codes: Mapped[list[int]] = mapped_column(JSON, default=lambda: [200], nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=5, nullable=False)
    failure_threshold: Mapped[int] = mapped_column(Integer, default=2, nullable=False)
    recovery_threshold: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consecutive_successes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str] = mapped_column(String(500), default="", nullable=False)

    service: Mapped[Service] = relationship(back_populates="health_check")


class HealthCheckResult(UUIDMixin, Base):
    __tablename__ = "health_check_results"
    __table_args__ = (
        Index("ix_hcr_workspace_service_time", "workspace_id", "service_id", "checked_at"),
        Index("ix_hcr_health_check_time", "health_check_id", "checked_at"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), nullable=False, index=True
    )
    health_check_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("health_checks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    status: Mapped[HealthResultStatus] = mapped_column(
        enum_column(HealthResultStatus, "health_result_status"), nullable=False
    )
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    error_kind: Mapped[str] = mapped_column(String(60), default="", nullable=False)
    error_message: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    effective_status: Mapped[ServiceStatus] = mapped_column(
        enum_column(ServiceStatus, "result_effective_status"),
        nullable=False,
        default=ServiceStatus.UNKNOWN,
    )


__all__ = [
    "Environment",
    "ServiceStatus",
    "HealthResultStatus",
    "Service",
    "HealthCheck",
    "HealthCheckResult",
]
