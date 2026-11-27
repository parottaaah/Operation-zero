"""add worker dead letters

Revision ID: 5ccac1b7640c
Revises: 2d7e7c869f2d
Create Date: 2026-11-27 12:52:33.971837
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '5ccac1b7640c'
down_revision: str | None = '2d7e7c869f2d'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker_dead_letters",
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(length=40), nullable=False),
        sa.Column("job_id", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=1000), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name=op.f("fk_worker_dead_letters_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_worker_dead_letters")),
        sa.UniqueConstraint("job_type", "job_id", name="uq_worker_dead_letter_job"),
    )
    with op.batch_alter_table("worker_dead_letters", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_worker_dead_letters_created_at"), ["created_at"], unique=False)
        batch_op.create_index(batch_op.f("ix_worker_dead_letters_workspace_id"), ["workspace_id"], unique=False)
        batch_op.create_index(
            "ix_worker_dead_letter_workspace_time", ["workspace_id", "created_at"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("worker_dead_letters", schema=None) as batch_op:
        batch_op.drop_index("ix_worker_dead_letter_workspace_time")
        batch_op.drop_index(batch_op.f("ix_worker_dead_letters_workspace_id"))
        batch_op.drop_index(batch_op.f("ix_worker_dead_letters_created_at"))
    op.drop_table("worker_dead_letters")
