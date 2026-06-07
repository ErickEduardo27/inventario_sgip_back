"""Tabla omnichannel_messages para historial inbox y envío por correo.

Revision ID: 008_omnichannel_messages
Revises: 007_contact_email
Create Date: 2026-05-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "008_omnichannel_messages"
down_revision = "007_contact_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "omnichannel_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_omnichannel_messages_contact_id"), "omnichannel_messages", ["contact_id"], unique=False
    )
    op.create_index(
        op.f("ix_omnichannel_messages_tenant_id"), "omnichannel_messages", ["tenant_id"], unique=False
    )
    op.create_index(
        "ix_omnichannel_messages_tenant_contact",
        "omnichannel_messages",
        ["tenant_id", "contact_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_omnichannel_messages_tenant_contact", table_name="omnichannel_messages")
    op.drop_index(op.f("ix_omnichannel_messages_tenant_id"), table_name="omnichannel_messages")
    op.drop_index(op.f("ix_omnichannel_messages_contact_id"), table_name="omnichannel_messages")
    op.drop_table("omnichannel_messages")
