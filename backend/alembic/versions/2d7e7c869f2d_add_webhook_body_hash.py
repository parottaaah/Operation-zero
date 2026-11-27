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
    # Scope both dedupe keys to the workspace so two tenants connected to the
    # same repository receive the same signed delivery independently.
    with op.batch_alter_table("webhook_events") as batch:
        batch.drop_constraint("uq_webhook_provider_delivery", type_="unique")
        batch.create_unique_constraint(
            "uq_webhook_workspace_provider_delivery",
            ["workspace_id", "provider", "delivery_id"],
        )
    op.add_column("webhook_events", sa.Column("body_sha256", sa.String(length=64), nullable=True))
    op.create_index(
        "uq_webhook_workspace_provider_body",
        "webhook_events",
        ["workspace_id", "provider", "body_sha256"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_webhook_workspace_provider_body", table_name="webhook_events")
    op.drop_column("webhook_events", "body_sha256")
    with op.batch_alter_table("webhook_events") as batch:
        batch.drop_constraint("uq_webhook_workspace_provider_delivery", type_="unique")
        batch.create_unique_constraint(
            "uq_webhook_provider_delivery",
            ["provider", "delivery_id"],
        )
