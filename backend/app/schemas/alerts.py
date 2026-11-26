"""Alert rule and alert schemas."""

from __future__ import annotations

import uuid

from pydantic import Field, model_validator

from app.models.alerting import AlertMetric, AlertSeverity, AlertStatus, Comparator
from app.schemas.common import APIModel, UtcDateTime


class AlertRuleCreate(APIModel):
    name: str = Field(min_length=1, max_length=160)
    metric: AlertMetric
    comparator: Comparator
    threshold: float
    service_id: uuid.UUID | None = None
    window_seconds: int = Field(default=300, ge=60, le=86_400)
    dedup_window_seconds: int = Field(default=1800, ge=60, le=86_400)
    severity: AlertSeverity = AlertSeverity.WARNING
    description: str = Field(default="", max_length=2000)
    enabled: bool = True
    notify_channels: list[str] = Field(default_factory=lambda: ["in_app"])

    @model_validator(mode="after")
    def validate_threshold(self) -> AlertRuleCreate:
        if self.metric in (AlertMetric.AVAILABILITY, AlertMetric.ERROR_RATE) and not (
            0 <= self.threshold <= 1
        ):
            raise ValueError("availability/error-rate thresholds must be between 0 and 1")
        if self.threshold < 0:
            raise ValueError("threshold must be non-negative")
        allowed = {"in_app", "email"}
        if set(self.notify_channels) - allowed:
            raise ValueError("notify_channels may only contain in_app and email")
        if not self.notify_channels:
            raise ValueError("at least one notification channel is required")
        return self


class AlertRuleUpdate(APIModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    metric: AlertMetric | None = None
    comparator: Comparator | None = None
    threshold: float | None = None
    service_id: uuid.UUID | None = None
    window_seconds: int | None = Field(default=None, ge=60, le=86_400)
    dedup_window_seconds: int | None = Field(default=None, ge=60, le=86_400)
    severity: AlertSeverity | None = None
    description: str | None = Field(default=None, max_length=2000)
    enabled: bool | None = None
    notify_channels: list[str] | None = None


class AlertRuleOut(APIModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    service_id: uuid.UUID | None
    name: str
    metric: AlertMetric
    comparator: Comparator
    threshold: float
    window_seconds: int
    dedup_window_seconds: int
    severity: AlertSeverity
    description: str
    enabled: bool
    notify_channels: list[str]
    last_evaluated_at: UtcDateTime | None
    created_at: UtcDateTime
    updated_at: UtcDateTime


class AlertOut(APIModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    rule_id: uuid.UUID
    rule_name: str | None = None
    service_id: uuid.UUID | None
    service_name: str | None = None
    incident_id: uuid.UUID | None
    status: AlertStatus
    severity: AlertSeverity
    title: str
    description: str
    trigger_value: float
    threshold: float
    window_seconds: int
    occurrence_count: int
    first_seen_at: UtcDateTime
    last_seen_at: UtcDateTime
    acknowledged_at: UtcDateTime | None
    muted_until: UtcDateTime | None
    resolved_at: UtcDateTime | None
    notified_at: UtcDateTime | None
    notified_channels: list[str]
    created_at: UtcDateTime


class AlertAcknowledge(APIModel):
    note: str = Field(default="", max_length=2000)


class AlertMute(APIModel):
    duration_minutes: int = Field(default=60, ge=5, le=10080)
    reason: str = Field(default="", max_length=500)


class AlertConvertToIncident(APIModel):
    title: str | None = Field(default=None, max_length=240)
    summary: str = Field(default="", max_length=8000)
    severity: AlertSeverity | None = None
    owner_id: uuid.UUID | None = None


class AlertEvaluateRequest(APIModel):
    rule_id: uuid.UUID | None = None


class AlertEvaluationOut(APIModel):
    rule_id: str
    service_id: str | None
    metric_value: float | None
    breached: bool
    alert_id: str | None
    action: str


__all__ = [
    "AlertRuleCreate",
    "AlertRuleUpdate",
    "AlertRuleOut",
    "AlertOut",
    "AlertAcknowledge",
    "AlertMute",
    "AlertConvertToIncident",
    "AlertEvaluateRequest",
    "AlertEvaluationOut",
]
