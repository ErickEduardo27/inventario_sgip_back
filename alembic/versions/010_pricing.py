"""WhatsApp: entrega/lectura y datos de pricing desde webhooks.

Revision ID: 010_pricing
Revises: 009_omnichannel_wa_message_id
Create Date: 2026-05-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "010_pricing"
down_revision = "009_omnichannel_wa_message_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "omnichannel_messages",
        sa.Column("wa_delivered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "omnichannel_messages",
        sa.Column("wa_read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "omnichannel_messages",
        sa.Column("wa_conversation_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "omnichannel_messages",
        sa.Column("wa_conversation_origin_type", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "omnichannel_messages",
        sa.Column("wa_billable", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "omnichannel_messages",
        sa.Column("wa_pricing_model", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "omnichannel_messages",
        sa.Column("wa_pricing_category", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "omnichannel_messages",
        sa.Column("wa_price_usd", sa.Numeric(12, 6), nullable=True),
    )
    op.add_column(
        "omnichannel_messages",
        sa.Column("wa_pricing_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index(
        op.f("ix_omnichannel_messages_wa_conversation_id"),
        "omnichannel_messages",
        ["wa_conversation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_omnichannel_messages_wa_conversation_id"), table_name="omnichannel_messages")
    op.drop_column("omnichannel_messages", "wa_pricing_snapshot")
    op.drop_column("omnichannel_messages", "wa_price_usd")
    op.drop_column("omnichannel_messages", "wa_pricing_category")
    op.drop_column("omnichannel_messages", "wa_pricing_model")
    op.drop_column("omnichannel_messages", "wa_billable")
    op.drop_column("omnichannel_messages", "wa_conversation_origin_type")
    op.drop_column("omnichannel_messages", "wa_conversation_id")
    op.drop_column("omnichannel_messages", "wa_read_at")
    op.drop_column("omnichannel_messages", "wa_delivered_at")
