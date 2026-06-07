"""Columna wa_message_id para correlacionar webhooks de estado de Meta.

Revision ID: 009_omnichannel_wa_message_id
Revises: 008_omnichannel_messages
Create Date: 2026-05-07
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "009_omnichannel_wa_message_id"
down_revision = "008_omnichannel_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "omnichannel_messages",
        sa.Column("wa_message_id", sa.String(length=255), nullable=True),
    )
    op.create_index(
        op.f("ix_omnichannel_messages_wa_message_id"),
        "omnichannel_messages",
        ["wa_message_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_omnichannel_messages_wa_message_id"), table_name="omnichannel_messages")
    op.drop_column("omnichannel_messages", "wa_message_id")
