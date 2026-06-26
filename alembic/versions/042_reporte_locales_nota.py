"""Reporte Locales: campo nota.

Revision ID: 042_reporte_locales_nota
Revises: 041_reporte_locales_files
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "042_reporte_locales_nota"
down_revision = "041_reporte_locales_files"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reporte_locales", sa.Column("nota", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("reporte_locales", "nota")
