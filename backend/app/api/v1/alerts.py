"""Alert rules, fired alerts, acknowledgement/mute and alert→incident conversion."""

from __future__ import annotations

import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import WorkspaceContext, require
from app.core.db import get_db
from app.core.errors import Conflict, NotFound, ValidationFailed
from app.core.permissions import Permission
from app.models.alerting import (
    Alert,
    AlertRule,
    AlertSeverity,
    AlertStatus,
)
from app.models.base import utcnow
from app.models.identity import Membership, User
from app.models.incident import EvidenceKind, IncidentStatus
from app.models.service import Service
from app.schemas.alerts import (
    AlertAcknowledge,
    AlertConvertToIncident,
    AlertEvaluationOut,
    AlertMute,
    AlertOut,
    AlertRuleCreate,
    AlertRuleOut,
    AlertRuleUpdate,
)
from app.schemas.common import CursorPage, Message
from app.services.alerts import evaluate_workspace
from app.services.audit import record_audit
from app.services.incidents import add_evidence, create_incident

router = APIRouter(prefix="/workspaces/{workspace_id}", tags=["alerts"])


def _get_rule(db: Session, workspace_id: uuid.UUID, rule_id: uuid.UUID) -> AlertRule:
    rule = db.get(AlertRule, rule_id)
    if rule is None or rule.workspace_id != workspace_id:
        raise NotFound("alert rule not found")
    return rule


def _get_alert(db: Session, workspace_id: uuid.UUID, alert_id: uuid.UUID) -> Alert:
    alert = db.get(Alert, alert_id)
    if alert is None or alert.workspace_id != workspace_id:
        raise NotFound("alert not found")
    return alert


def _validate_service(db: Session, workspace_id: uuid.UUID, service_id: uuid.UUID | None):
    if service_id is None:
        return
    service = db.get(Service, service_id)
    if service is None or service.workspace_id != workspace_id:
        raise NotFound("service not found")


def _alert_out(db: Session, alert: Alert) -> AlertOut:
    rule = db.get(AlertRule, alert.rule_id)
    service = db.get(Service, alert.service_id) if alert.service_id else None
    return AlertOut(
        **{
            column.name: getattr(alert, column.name)
            for column in Alert.__table__.columns
            if column.name
            in {
                "id",
                "workspace_id",
                "rule_id",
                "service_id",
                "incident_id",
                "status",
                "severity",
                "title",
                "description",
                "trigger_value",
                "threshold",
                "window_seconds",
                "occurrence_count",
                "first_seen_at",
                "last_seen_at",
                "acknowledged_at",
                "muted_until",
                "resolved_at",
                "notified_at",
                "notified_channels",
                "created_at",
            }
        },
        rule_name=rule.name if rule else None,
        service_name=service.name if service else None,
    )


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------
@router.post("/alert-rules", response_model=AlertRuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(
    payload: AlertRuleCreate,
    context: WorkspaceContext = Depends(require(Permission.ALERTS_WRITE)),
    db: Session = Depends(get_db),
) -> AlertRuleOut:
    _validate_service(db, context.workspace_id, payload.service_id)
    rule = AlertRule(
        workspace_id=context.workspace_id,
        service_id=payload.service_id,
        name=payload.name,
        metric=payload.metric,
        comparator=payload.comparator,
        threshold=payload.threshold,
        window_seconds=payload.window_seconds,
        dedup_window_seconds=payload.dedup_window_seconds,
        severity=payload.severity,
        description=payload.description,
        enabled=payload.enabled,
        notify_channels=payload.notify_channels,
        created_by_id=context.user.id,
    )
    db.add(rule)
    db.flush()
    record_audit(
        db,
        action="alert_rule.create",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="alert_rule",
        target_id=rule.id,
        request_id=context.request_id,
        metadata={
            "metric": rule.metric.value,
            "threshold": rule.threshold,
            "window_seconds": rule.window_seconds,
        },
    )
    db.commit()
    db.refresh(rule)
    return AlertRuleOut.model_validate(rule)


@router.get("/alert-rules", response_model=list[AlertRuleOut])
def list_rules(
    context: WorkspaceContext = Depends(require(Permission.ALERTS_READ)),
    db: Session = Depends(get_db),
) -> list[AlertRuleOut]:
    rows = (
        db.query(AlertRule)
        .filter(AlertRule.workspace_id == context.workspace_id)
        .order_by(AlertRule.created_at.desc())
        .all()
    )
    return [AlertRuleOut.model_validate(row) for row in rows]


@router.patch("/alert-rules/{rule_id}", response_model=AlertRuleOut)
def update_rule(
    rule_id: uuid.UUID,
    payload: AlertRuleUpdate,
    context: WorkspaceContext = Depends(require(Permission.ALERTS_WRITE)),
    db: Session = Depends(get_db),
) -> AlertRuleOut:
    rule = _get_rule(db, context.workspace_id, rule_id)
    changes = payload.model_dump(exclude_unset=True)
    if "service_id" in changes:
        _validate_service(db, context.workspace_id, changes["service_id"])
    for key, value in changes.items():
        setattr(rule, key, value)
    record_audit(
        db,
        action="alert_rule.update",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="alert_rule",
        target_id=rule.id,
        request_id=context.request_id,
        metadata={"fields": sorted(changes)},
    )
    db.commit()
    db.refresh(rule)
    return AlertRuleOut.model_validate(rule)


@router.delete("/alert-rules/{rule_id}", response_model=Message)
def delete_rule(
    rule_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.ALERTS_WRITE)),
    db: Session = Depends(get_db),
) -> Message:
    rule = _get_rule(db, context.workspace_id, rule_id)
    record_audit(
        db,
        action="alert_rule.delete",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="alert_rule",
        target_id=rule.id,
        request_id=context.request_id,
        metadata={"name": rule.name},
    )
    db.delete(rule)
    db.commit()
    return Message(message="alert rule deleted")


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
@router.get("/alerts", response_model=CursorPage[AlertOut])
def list_alerts(
    alert_status: AlertStatus | None = Query(default=None, alias="status"),
    severity: AlertSeverity | None = None,
    service_id: uuid.UUID | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor: str | None = None,
    context: WorkspaceContext = Depends(require(Permission.ALERTS_READ)),
    db: Session = Depends(get_db),
) -> CursorPage[AlertOut]:
    from app.core.pagination import paginate

    filters = [Alert.workspace_id == context.workspace_id]
    if alert_status is not None:
        filters.append(Alert.status == alert_status)
    if severity is not None:
        filters.append(Alert.severity == severity)
    if service_id is not None:
        filters.append(Alert.service_id == service_id)
    rows, next_cursor = paginate(
        db,
        Alert,
        filters=filters,
        order_column=Alert.created_at,
        limit=limit,
        cursor=cursor,
    )
    return CursorPage(
        items=[_alert_out(db, row) for row in rows],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge_alert(
    alert_id: uuid.UUID,
    payload: AlertAcknowledge | None = None,
    context: WorkspaceContext = Depends(require(Permission.ALERTS_WRITE)),
    db: Session = Depends(get_db),
) -> AlertOut:
    alert = _get_alert(db, context.workspace_id, alert_id)
    if alert.status is AlertStatus.RESOLVED:
        raise Conflict("a resolved alert cannot be acknowledged")
    alert.status = AlertStatus.ACKNOWLEDGED
    alert.acknowledged_by_id = context.user.id
    alert.acknowledged_at = utcnow()
    record_audit(
        db,
        action="alert.acknowledge",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="alert",
        target_id=alert.id,
        request_id=context.request_id,
        metadata={"note": (payload.note if payload else "")[:500]},
    )
    db.commit()
    db.refresh(alert)
    return _alert_out(db, alert)


@router.post("/alerts/{alert_id}/mute", response_model=AlertOut)
def mute_alert(
    alert_id: uuid.UUID,
    payload: AlertMute,
    context: WorkspaceContext = Depends(require(Permission.ALERTS_WRITE)),
    db: Session = Depends(get_db),
) -> AlertOut:
    alert = _get_alert(db, context.workspace_id, alert_id)
    alert.status = AlertStatus.MUTED
    alert.muted_by_id = context.user.id
    alert.muted_until = utcnow() + timedelta(minutes=payload.duration_minutes)
    record_audit(
        db,
        action="alert.mute",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="alert",
        target_id=alert.id,
        request_id=context.request_id,
        metadata={
            "duration_minutes": payload.duration_minutes,
            "reason": payload.reason[:200],
        },
    )
    db.commit()
    db.refresh(alert)
    return _alert_out(db, alert)


@router.post("/alerts/{alert_id}/resolve", response_model=AlertOut)
def resolve_alert(
    alert_id: uuid.UUID,
    context: WorkspaceContext = Depends(require(Permission.ALERTS_WRITE)),
    db: Session = Depends(get_db),
) -> AlertOut:
    alert = _get_alert(db, context.workspace_id, alert_id)
    alert.status = AlertStatus.RESOLVED
    alert.resolved_at = utcnow()
    record_audit(
        db,
        action="alert.resolve",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="alert",
        target_id=alert.id,
        request_id=context.request_id,
    )
    db.commit()
    db.refresh(alert)
    return _alert_out(db, alert)


@router.post("/alerts/{alert_id}/to-incident", response_model=dict)
def convert_to_incident(
    alert_id: uuid.UUID,
    payload: AlertConvertToIncident,
    context: WorkspaceContext = Depends(require(Permission.INCIDENTS_WRITE)),
    db: Session = Depends(get_db),
) -> dict:
    alert = _get_alert(db, context.workspace_id, alert_id)
    if alert.incident_id is not None:
        raise Conflict("alert has already been converted to an incident")
    if payload.owner_id is not None:
        membership = (
            db.query(Membership)
            .filter(
                Membership.workspace_id == context.workspace_id,
                Membership.user_id == payload.owner_id,
            )
            .first()
        )
        if membership is None:
            raise ValidationFailed("owner must be a member of this workspace")
    service = db.get(Service, alert.service_id) if alert.service_id else None
    title = payload.title or f"{alert.title} · {service.name if service else 'workspace'}"
    incident = create_incident(
        db,
        workspace_id=context.workspace_id,
        actor=context.user,
        title=title,
        summary=payload.summary or alert.description,
        severity=payload.severity or alert.severity,
        status=IncidentStatus.OPEN,
        service_id=alert.service_id,
        owner_id=payload.owner_id,
        detected_at=alert.first_seen_at,
        alert=alert,
        request_id=context.request_id,
    )
    alert.incident_id = incident.id
    if alert.status is AlertStatus.FIRING:
        alert.status = AlertStatus.ACKNOWLEDGED
        alert.acknowledged_by_id = context.user.id
        alert.acknowledged_at = utcnow()
    add_evidence(
        db,
        incident,
        actor=context.user,
        kind=EvidenceKind.NOTE,
        title=f"Alert: {alert.title}",
        excerpt=alert.description,
        metadata={"alert_id": str(alert.id), "trigger_value": alert.trigger_value},
        request_id=context.request_id,
    )
    record_audit(
        db,
        action="alert.convert_to_incident",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="incident",
        target_id=incident.id,
        request_id=context.request_id,
        metadata={"alert_id": str(alert.id)},
    )
    db.commit()
    return {
        "incident_id": str(incident.id),
        "alert_id": str(alert.id),
        "status": incident.status.value,
        "owner_id": str(incident.owner_id) if incident.owner_id else None,
    }


@router.post("/alerts/evaluate", response_model=list[AlertEvaluationOut])
def evaluate_alerts_now(
    context: WorkspaceContext = Depends(require(Permission.ALERTS_WRITE)),
    db: Session = Depends(get_db),
) -> list[AlertEvaluationOut]:
    outcomes = evaluate_workspace(db, context.workspace_id)
    record_audit(
        db,
        action="alerts.evaluate",
        workspace_id=context.workspace_id,
        actor_id=context.user.id,
        actor_email=context.user.email,
        target_type="alert_rule",
        target_id="all",
        request_id=context.request_id,
        metadata={"rules_evaluated": len(outcomes)},
    )
    db.commit()
    return [
        AlertEvaluationOut(
            rule_id=outcome.rule_id,
            service_id=outcome.service_id,
            metric_value=outcome.metric_value,
            breached=outcome.breached,
            alert_id=outcome.alert_id,
            action=outcome.action,
        )
        for outcome in outcomes
    ]


__all__ = ["router", "User"]
