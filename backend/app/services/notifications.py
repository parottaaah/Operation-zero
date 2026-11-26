"""Notification fan-out for alerts (email is optional and never required)."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.alerting import Alert
from app.models.base import utcnow
from app.models.identity import Membership, User
from app.models.platform import Notification, NotificationStatus
from app.models.service import Service

logger = logging.getLogger(__name__)


def _deliver_email(recipient: str, subject: str, body: str) -> tuple[bool, str]:
    if not settings.smtp_host:
        # Console transport for local/dev and pilots without SMTP. The message is
        # persisted in-app, so no notification content is lost.
        logger.info("email transport not configured; suppressed message to %s", recipient)
        return True, ""
    try:
        message = EmailMessage()
        message["From"] = settings.email_from
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
            if settings.smtp_starttls:
                smtp.starttls()
            if settings.smtp_username:
                smtp.login(settings.smtp_username, settings.smtp_password)
            smtp.send_message(message)
        return True, ""
    except Exception as exc:  # pragma: no cover - network dependent
        logger.warning("email delivery failed: %s", type(exc).__name__)
        return False, type(exc).__name__


def notify_alert(session: Session, alert: Alert) -> list[str]:
    """Create in-app notifications and optionally send email. Returns channels used."""
    service = session.get(Service, alert.service_id) if alert.service_id else None
    service_label = f" · {service.name}" if service else ""
    subject = f"[{alert.severity.value.upper()}] {alert.title}{service_label}"
    body = (
        f"{alert.description}\n\n"
        f"Observed value: {alert.trigger_value:.4g} (threshold {alert.threshold:.4g})\n"
        f"Window: {alert.window_seconds}s\n"
        f"Occurrences: {alert.occurrence_count}\n"
        "Open OPERATION ZERO to acknowledge, mute or convert this alert to an incident."
    )

    recipients = (
        session.query(User)
        .join(Membership, Membership.user_id == User.id)
        .filter(
            Membership.workspace_id == alert.workspace_id,
            User.is_active.is_(True),
            Membership.role.in_(["owner", "admin", "engineer", "security_analyst"]),
        )
        .all()
    )

    from app.models.alerting import AlertRule

    rule = session.get(AlertRule, alert.rule_id) if alert.rule_id else None
    configured_channels = (rule.notify_channels if rule else None) or ["in_app"]

    channels: list[str] = []
    now = utcnow()
    if "in_app" in configured_channels:
        for user in recipients:
            session.add(
                Notification(
                    workspace_id=alert.workspace_id,
                    user_id=user.id,
                    channel="in_app",
                    subject=subject,
                    body=body,
                    related_type="alert",
                    related_id=str(alert.id),
                    status=NotificationStatus.SENT,
                    created_at=now,
                    sent_at=now,
                )
            )
        channels.append("in_app")

    if "email" in configured_channels:
        sent_any = False
        for user in recipients:
            delivered, error = _deliver_email(user.email, subject, body)
            session.add(
                Notification(
                    workspace_id=alert.workspace_id,
                    user_id=user.id,
                    channel="email",
                    subject=subject,
                    body=body,
                    related_type="alert",
                    related_id=str(alert.id),
                    status=NotificationStatus.SENT if delivered else NotificationStatus.FAILED,
                    error=error,
                    created_at=now,
                    sent_at=now if delivered else None,
                )
            )
            sent_any = sent_any or delivered
        if sent_any:
            channels.append("email")

    alert.notified_at = now
    alert.notified_channels = channels
    return channels


__all__ = ["notify_alert"]
