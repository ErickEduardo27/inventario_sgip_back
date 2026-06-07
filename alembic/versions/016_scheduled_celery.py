"""scheduled_messages: id de tarea Celery (cola Redis).

Revision ID: 016_scheduled_celery
Revises: 015_scheduled_message
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "016_scheduled_celery"
down_revision = "015_scheduled_message"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduled_messages",
        sa.Column("celery_task_id", sa.String(length=120), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scheduled_messages", "celery_task_id")
