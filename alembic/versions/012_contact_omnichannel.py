"""contacts: última lectura omnicanal para contador no leídos.

Revision ID: 012_contact_omnichannel
Revises: 011_message_templates_meta
Create Date: 2026-05-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "012_contact_omnichannel"
down_revision = "011_message_templates_meta"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("omnichannel_last_read_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        sa.text("UPDATE contacts SET omnichannel_last_read_at = NOW() WHERE omnichannel_last_read_at IS NULL")
    )


def downgrade() -> None:
    op.drop_column("contacts", "omnichannel_last_read_at")
