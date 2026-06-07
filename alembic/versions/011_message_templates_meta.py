"""message_templates: campos sincronización Meta (WABA).

Revision ID: 011_message_templates_meta
Revises: 010_pricing
Create Date: 2026-05-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "011_message_templates_meta"
down_revision = "010_pricing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "message_templates",
        sa.Column("wa_meta_name", sa.String(length=512), nullable=True),
    )
    op.add_column(
        "message_templates",
        sa.Column("wa_language", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "message_templates",
        sa.Column("wa_meta_category", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "message_templates",
        sa.Column("wa_review_status", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "message_templates",
        sa.Column("wa_review_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "message_templates",
        sa.Column("wa_submitted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "message_templates",
        sa.Column("wa_graph_template_id", sa.String(length=128), nullable=True),
    )
    op.create_index(
        op.f("ix_message_templates_wa_meta_name"),
        "message_templates",
        ["wa_meta_name"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_message_templates_wa_meta_name"), table_name="message_templates")
    op.drop_column("message_templates", "wa_graph_template_id")
    op.drop_column("message_templates", "wa_submitted_at")
    op.drop_column("message_templates", "wa_review_reason")
    op.drop_column("message_templates", "wa_review_status")
    op.drop_column("message_templates", "wa_meta_category")
    op.drop_column("message_templates", "wa_language")
    op.drop_column("message_templates", "wa_meta_name")
