"""Contadores de numeración de hojas y etiquetas por usuario inventario.

Revision ID: 020_user_inventory_counters
Revises: 019_establishment_photo
Create Date: 2026-06-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "020_user_inventory_counters"
down_revision = "019_establishment_photo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("num_ini", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("num_fin", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("num_act", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("eti_ini", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("eti_fin", sa.Integer(), nullable=True))
    op.add_column("users", sa.Column("eti_act", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "eti_act")
    op.drop_column("users", "eti_fin")
    op.drop_column("users", "eti_ini")
    op.drop_column("users", "num_act")
    op.drop_column("users", "num_fin")
    op.drop_column("users", "num_ini")
