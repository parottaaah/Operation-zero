"""Alert evaluation, deduplication and automatic resolution.

The evaluator is deliberately deterministic and bounded: every query is scoped to
one workspace, one rule and one time window.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.alerting import (
    Alert,
    AlertMetric,
    AlertRule,
    AlertStatus,
    Comparator,
)
from app.models.base import utcnow
from app.models.service import HealthCheckResult, HealthResultStatus
from app.models.telemetry import LogEvent, Severity
from app.services.notifications import notify_alert

logger = logging.getLogger(__name__)


@dataclass
class EvaluationOutcome:
    rule_id: str
    service_id: str | None
    metric_value: float | None
    breached: bool
    alert_id: str | None = None
    action: str = "none"


def _compare(value: float, comparator: Comparator, threshold: float) -> bool:
    if comparator is Comparator.GT:
        return value > threshold
    if comparator is Comparator.GTE:
        return value >= threshold
    if comparator is Comparator.LT:
        return value < threshold
    return value <= threshold


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(pct / 100 * len(ordered)) - 1)
    return ordered[index]


def compute_metric(
    session: Session,
    rule: AlertRule,
    window_start,
    window_end,
) -> float | None:
    query_filters = [
        HealthCheckResult.workspace_id == rule.workspace_id,
        HealthCheckResult.checked_at >= window_start,
        HealthCheckResult.checked_at <= window_end,
    ]
    if rule.service_id is not None:
        query_filters.append(HealthCheckResult.service_id == rule.service_id)

    if rule.metric is AlertMetric.AVAILABILITY:
        total = session.query(func.count(HealthCheckResult.id)).filter(*query_filters).scalar() or 0
        if not total:
            return None
        passed = (
            session.query(func.count(HealthCheckResult.id))
            .filter(*query_filters, HealthCheckResult.status == HealthResultStatus.PASS)
            .scalar()
            or 0
        )
        return passed / total

    if rule.metric is AlertMetric.LATENCY_P95:
        values = [
            row[0]
            for row in session.query(HealthCheckResult.latency_ms)
            .filter(*query_filters, HealthCheckResult.latency_ms.isnot(None))
            .all()
        ]
        return _percentile([float(v) for v in values], 95)

    log_filters = [
        LogEvent.workspace_id == rule.workspace_id,
        LogEvent.event_timestamp >= window_start,
        LogEvent.event_timestamp <= window_end,
    ]
    if rule.service_id is not None:
        log_filters.append(LogEvent.service_id == rule.service_id)

    if rule.metric is AlertMetric.ERROR_COUNT:
        return float(
            session.query(func.count(LogEvent.id))
            .filter(*log_filters, LogEvent.severity.in_([Severity.ERROR, Severity.CRITICAL]))
            .scalar()
            or 0
        )

    if rule.metric is AlertMetric.ERROR_RATE:
        total = session.query(func.count(LogEvent.id)).filter(*log_filters).scalar() or 0
        if not total:
            return None
        errors = (
            session.query(func.count(LogEvent.id))
            .filter(*log_filters, LogEvent.severity.in_([Severity.ERROR, Severity.CRITICAL]))
            .scalar()
            or 0
        )
        return errors / total

    return None


def _format_value(metric: AlertMetric, value: float) -> str:
    if metric in (AlertMetric.AVAILABILITY, AlertMetric.ERROR_RATE):
        return f"{value * 100:.1f}%"
    if metric is AlertMetric.LATENCY_P95:
        return f"{value:.0f} ms"
    return f"{value:.0f}"


def evaluate_rule(session: Session, rule: AlertRule, *, now=None, notify: bool = True) -> EvaluationOutcome:
    now = now or utcnow()
    window_start = now - timedelta(seconds=rule.window_seconds)
    value = compute_metric(session, rule, window_start, now)
    rule.last_evaluated_at = now

    dedup_key = f"{rule.id}:{rule.service_id or 'workspace'}"

    if value is None:
        return EvaluationOutcome(str(rule.id), str(rule.service_id or "") or None, None, False)

    breached = _compare(value, rule.comparator, rule.threshold)
    open_alerts = (
        session.query(Alert)
        .filter(
            Alert.workspace_id == rule.workspace_id,
            Alert.dedup_key == dedup_key,
            Alert.status.in_([AlertStatus.FIRING, AlertStatus.ACKNOWLEDGED, AlertStatus.MUTED]),
        )
        .order_by(Alert.created_at.desc())
        .all()
    )

    if breached:
        existing = open_alerts[0] if open_alerts else None
        if existing is not None and existing.last_seen_at >= now - timedelta(
            seconds=rule.dedup_window_seconds
        ):
            existing.occurrence_count += 1
            existing.last_seen_at = now
            existing.trigger_value = value
            if existing.status is AlertStatus.MUTED and existing.muted_until and existing.muted_until <= now:
                existing.status = AlertStatus.FIRING
                existing.muted_until = None
                if notify:
                    notify_alert(session, existing)
            return EvaluationOutcome(
                str(rule.id),
                str(rule.service_id) if rule.service_id else None,
                value,
                True,
                str(existing.id),
                "deduplicated",
            )

        alert = Alert(
            workspace_id=rule.workspace_id,
            rule_id=rule.id,
            service_id=rule.service_id,
            status=AlertStatus.FIRING,
            severity=rule.severity,
            title=f"{rule.name} breached",
            description=(
                f"{rule.metric.value} is {_format_value(rule.metric, value)} over the last "
                f"{rule.window_seconds}s, breaching the {rule.comparator.value} threshold of "
                f"{_format_value(rule.metric, rule.threshold)}."
            ),
            trigger_value=value,
            threshold=rule.threshold,
            window_seconds=rule.window_seconds,
            dedup_key=dedup_key,
            occurrence_count=1,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(alert)
        session.flush()
        if notify:
            notify_alert(session, alert)
        return EvaluationOutcome(
            str(rule.id),
            str(rule.service_id) if rule.service_id else None,
            value,
            True,
            str(alert.id),
            "created",
        )

    # Not breaching: auto-resolve firing alerts that have stopped seeing failures.
    resolved_any = False
    for alert in open_alerts:
        if alert.status is AlertStatus.FIRING and alert.last_seen_at <= now - timedelta(
            seconds=rule.window_seconds
        ):
            alert.status = AlertStatus.RESOLVED
            alert.resolved_at = now
            resolved_any = True
    return EvaluationOutcome(
        str(rule.id),
        str(rule.service_id) if rule.service_id else None,
        value,
        False,
        None,
        "auto_resolved" if resolved_any else "none",
    )


def evaluate_workspace(session: Session, workspace_id, *, now=None) -> list[EvaluationOutcome]:
    rules = (
        session.query(AlertRule)
        .filter(AlertRule.workspace_id == workspace_id, AlertRule.enabled.is_(True))
        .all()
    )
    return [evaluate_rule(session, rule, now=now) for rule in rules]


def evaluate_all(session: Session, *, now=None, batch_size: int = 200) -> list[EvaluationOutcome]:
    rules = (
        session.query(AlertRule)
        .filter(AlertRule.enabled.is_(True))
        .order_by(AlertRule.last_evaluated_at.asc().nullsfirst())
        .limit(batch_size)
        .all()
    )
    return [evaluate_rule(session, rule, now=now) for rule in rules]


__all__ = [
    "EvaluationOutcome",
    "compute_metric",
    "evaluate_rule",
    "evaluate_workspace",
    "evaluate_all",
]
