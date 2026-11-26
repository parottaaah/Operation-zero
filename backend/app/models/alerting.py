"""Alert rules, fired alerts and deduplication."""

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
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDMixin, enum_column


class AlertMetric(str, enum.Enum):
    AVAILABILITY = "availability"  # fraction of successful health checks (0..1)
    ERROR_COUNT = "error_count"  # count of error/critical log events
    ERROR_RATE = "error_rate"  # error events / total events (0..1)
    LATENCY_P95 = "latency_p95"  # p95 health-check latency in milliseconds


class Comparator(str, enum.Enum):
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"


class AlertSeverity(str, enum.Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertStatus(str, enum.Enum):
    FIRING = "firing"
    ACKNOWLEDGED = "acknowledged"
    MUTED = "muted"
    RESOLVED = "resolved"


class NotificationChannel(str, enum.Enum):
    IN_APP = "in_app"
    EMAIL = "email"


class AlertRule(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "alert_rules"
    __table_args__ = (Index("ix_alert_rules_workspace_enabled", "workspace_id", "enabled"),)

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("services.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    metric: Mapped[AlertMetric] = mapped_column(enum_column(AlertMetric, "alert_metric"), nullable=False)
    comparator: Mapped[Comparator] = mapped_column(
        enum_column(Comparator, "alert_comparator"), nullable=False
    )
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    dedup_window_seconds: Mapped[int] = mapped_column(Integer, default=1800, nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(
        enum_column(AlertSeverity, "alert_severity"), nullable=False, default=AlertSeverity.WARNING
    )
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    notify_channels: Mapped[list[str]] = mapped_column(JSON, default=lambda: ["in_app"], nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    last_evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)


class Alert(UUIDMixin, TimestampMixin, Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_workspace_status", "workspace_id", "status", "created_at"),
        Index("ix_alerts_dedup", "workspace_id", "rule_id", "service_id", "status"),
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    service_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("services.id", ondelete="SET NULL"), nullable=True, index=True
    )
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[AlertStatus] = mapped_column(
        enum_column(AlertStatus, "alert_status"), nullable=False, default=AlertStatus.FIRING
    )
    severity: Mapped[AlertSeverity] = mapped_column(
        enum_column(AlertSeverity, "alert_rule_severity"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    trigger_value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False)
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    muted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    muted_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=False), nullable=True)
    notified_channels: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)


__all__ = [
    "AlertMetric",
    "Comparator",
    "AlertSeverity",
    "AlertStatus",
    "NotificationChannel",
    "AlertRule",
    "Alert",
]
