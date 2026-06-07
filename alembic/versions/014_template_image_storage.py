"""message_templates: blob + token público para cabecera IMAGE (Meta).

Revision ID: 014_template_image_storage
Revises: 013_message_temple_image
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "014_template_image_storage"
down_revision = "013_message_temple_image"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "message_templates",
        sa.Column("wa_header_image_mime", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "message_templates",
        sa.Column("wa_header_image_blob", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "message_templates",
        sa.Column("wa_header_image_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_message_templates_wa_header_image_token",
        "message_templates",
        ["wa_header_image_token"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_message_templates_wa_header_image_token", table_name="message_templates")
    op.drop_column("message_templates", "wa_header_image_token")
    op.drop_column("message_templates", "wa_header_image_blob")
    op.drop_column("message_templates", "wa_header_image_mime")
