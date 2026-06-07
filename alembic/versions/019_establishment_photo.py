"""Foto de fachada para establecimientos (locales), almacenada en BD.

Revision ID: 019_establishment_photo
Revises: 018_latitude_longitude
Create Date: 2026-05-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "019_establishment_photo"
down_revision = "018_latitude_longitude"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("establishments", sa.Column("photo_mime", sa.String(length=100), nullable=True))
    op.add_column("establishments", sa.Column("photo_blob", sa.LargeBinary(), nullable=True))
    op.add_column(
        "establishments",
        sa.Column("photo_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(op.f("ix_establishments_photo_token"), "establishments", ["photo_token"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_establishments_photo_token"), table_name="establishments")
    op.drop_column("establishments", "photo_token")
    op.drop_column("establishments", "photo_blob")
    op.drop_column("establishments", "photo_mime")
