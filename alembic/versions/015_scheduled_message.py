"""scheduled_messages: nombre visible del envío programado.

Revision ID: 015_scheduled_message
Revises: 014_template_image_storage
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "015_scheduled_message"
down_revision = "014_template_image_storage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "scheduled_messages",
        sa.Column("display_name", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("scheduled_messages", "display_name")
