"""Agrega latitud y longitud a establecimientos (locales).

Revision ID: 018_latitude_longitude
Revises: 017_inventory_grupo_iso
Create Date: 2026-05-23
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "018_latitude_longitude"
down_revision = "017_inventory_grupo_iso"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("establishments", sa.Column("latitude", sa.Float(), nullable=True))
    op.add_column("establishments", sa.Column("longitude", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("establishments", "longitude")
    op.drop_column("establishments", "latitude")
