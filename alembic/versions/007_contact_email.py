"""Agrega correo electrónico a contactos.

Revision ID: 007_contact_email
Revises: 006_campaign_status
Create Date: 2026-05-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "007_contact_email"
down_revision = "006_campaign_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "contacts",
        sa.Column("email", sa.String(length=254), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("contacts", "email")
