"""Model package — importing this registers every table on ``Base.metadata``."""

from app.models.ai import AIAnalysis, AIAnalysisStatus, AIFeedback
from app.models.alerting import (
    Alert,
    AlertMetric,
    AlertRule,
    AlertSeverity,
    AlertStatus,
    Comparator,
    NotificationChannel,
)
from app.models.audit import AuditEvent
from app.models.base import Base, utcnow
from app.models.identity import ROLE_RANK, Membership, Role, User, Workspace
from app.models.incident import (
    INCIDENT_TRANSITIONS,
    EvidenceKind,
    EvidenceLink,
    Incident,
    IncidentEvent,
    IncidentEventType,
    IncidentStatus,
)
from app.models.integration import (
    Integration,
    IntegrationProvider,
    IntegrationStatus,
    WebhookEvent,
    WebhookStatus,
)
from app.models.platform import IdempotencyKey, Notification, NotificationStatus, Report
from app.models.service import (
    Environment,
    HealthCheck,
    HealthCheckResult,
    HealthResultStatus,
    Service,
    ServiceStatus,
)
from app.models.telemetry import LogEvent, Severity

__all__ = [
    "Base",
    "utcnow",
    "User",
    "Workspace",
    "Membership",
    "Role",
    "ROLE_RANK",
    "Service",
    "HealthCheck",
    "HealthCheckResult",
    "Environment",
    "ServiceStatus",
    "HealthResultStatus",
    "LogEvent",
    "Severity",
    "AlertRule",
    "Alert",
    "AlertMetric",
    "AlertSeverity",
    "AlertStatus",
    "Comparator",
    "NotificationChannel",
    "Incident",
    "IncidentEvent",
    "IncidentStatus",
    "IncidentEventType",
    "EvidenceLink",
    "EvidenceKind",
    "INCIDENT_TRANSITIONS",
    "Integration",
    "IntegrationProvider",
    "IntegrationStatus",
    "WebhookEvent",
    "WebhookStatus",
    "AIAnalysis",
    "AIAnalysisStatus",
    "AIFeedback",
    "AuditEvent",
    "Notification",
    "NotificationStatus",
    "IdempotencyKey",
    "Report",
]
