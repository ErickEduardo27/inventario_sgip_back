"""message_templates: cabecera IMAGE y botones quick reply para Meta.

Revision ID: 013_message_temple_image
Revises: 012_contact_omnichannel
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "013_message_temple_image"
down_revision = "012_contact_omnichannel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "message_templates",
        sa.Column("wa_header_format", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "message_templates",
        sa.Column(
            "wa_quick_reply_buttons",
            postgresql.ARRAY(sa.String(length=40)),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("message_templates", "wa_quick_reply_buttons")
    op.drop_column("message_templates", "wa_header_format")
