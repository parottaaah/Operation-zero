"""The demo seed must work twice in a row and stay tenant-scoped."""

from __future__ import annotations

from sqlalchemy import func, select

from app.core.security import verify_password
from app.models import (
    Alert,
    EvidenceLink,
    Incident,
    LogEvent,
    Membership,
    Notification,
    Service,
    User,
    WebhookEvent,
    Workspace,
)
from app.models.ai import AIAnalysis
from app.scripts.seed_demo import (
    DEMO_PASSWORD,
    DEMO_USERS,
    DEMO_WORKSPACE_SLUG,
    seed_demo,
)


def _count(db, model) -> int:
    return db.execute(select(func.count()).select_from(model)).scalar_one()


def test_seed_creates_explorable_demo_workspace(db):
    summary = seed_demo(db)
    db.commit()

    assert summary.created is True
    assert db.execute(select(Workspace).where(Workspace.slug == DEMO_WORKSPACE_SLUG)).scalar_one()

    assert _count(db, Service) == 4
    assert _count(db, Incident) == 3
    assert _count(db, Alert) == 2
    assert _count(db, WebhookEvent) == 2
    assert _count(db, EvidenceLink) == 8
    assert _count(db, AIAnalysis) == 1
    assert _count(db, LogEvent) >= 10
    assert summary.log_events == _count(db, LogEvent)

    for email, _role in summary.accounts:
        user = db.execute(select(User).where(User.email == email)).scalar_one()
        assert verify_password(DEMO_PASSWORD, user.password_hash)
    assert _count(db, User) == len(DEMO_USERS)
    assert _count(db, Membership) == len(DEMO_USERS)


def test_seed_is_idempotent(db):
    first = seed_demo(db)
    db.commit()
    services_before = _count(db, Service)
    logs_before = _count(db, LogEvent)

    second = seed_demo(db)
    db.commit()

    assert first.created is True
    assert second.created is False
    assert second.workspace_id == first.workspace_id
    assert _count(db, Service) == services_before
    assert _count(db, LogEvent) == logs_before
    assert _count(db, Workspace) == 1


def test_seed_force_replaces_demo_data(db):
    first = seed_demo(db)
    db.commit()
    services_before = _count(db, Service)

    rebuilt = seed_demo(db, force=True)
    db.commit()

    assert rebuilt.created is True
    assert rebuilt.workspace_id == first.workspace_id
    assert _count(db, Workspace) == 1
    assert _count(db, Service) == services_before
    assert _count(db, User) == len(DEMO_USERS)
    # Demo data must never leak outside the demo workspace.
    orphan_incidents = db.execute(
        select(func.count()).select_from(Incident).where(Incident.workspace_id != first.workspace_id)
    ).scalar_one()
    assert orphan_incidents == 0


def test_seeded_data_is_redacted(db):
    seed_demo(db)
    db.commit()

    dsn_rows = db.execute(select(LogEvent.message).where(LogEvent.message.like("%SuperSecret%"))).all()
    assert dsn_rows == []

    redacted = db.execute(
        select(func.count()).select_from(LogEvent).where(LogEvent.redaction_count > 0)
    ).scalar_one()
    assert redacted >= 1
    assert _count(db, Notification) >= 1
