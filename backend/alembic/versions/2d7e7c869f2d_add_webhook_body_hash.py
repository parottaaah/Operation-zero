"""add webhook body hash

Revision ID: 2d7e7c869f2d
Revises: 1c406a06f398
Create Date: 2026-11-27 12:34:03.737810
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '2d7e7c869f2d'
down_revision: str | None = '1c406a06f398'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("webhook_events", sa.Column("body_sha256", sa.String(length=64), nullable=True))
    op.create_index(
        "uq_webhook_provider_body_sha256",
        "webhook_events",
        ["provider", "body_sha256"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_webhook_provider_body_sha256", table_name="webhook_events")
    op.drop_column("webhook_events", "body_sha256")
