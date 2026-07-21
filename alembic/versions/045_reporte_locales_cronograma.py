"""Reporte Locales: fechas de cronograma.

Revision ID: 045_reporte_locales_cronograma
Revises: 044_reporte_locales_grupo
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "045_reporte_locales_cronograma"
down_revision = "044_reporte_locales_grupo"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reporte_locales",
        sa.Column("fecha_inicio_cronograma", sa.Date(), nullable=True),
    )
    op.add_column(
        "reporte_locales",
        sa.Column("fecha_cierre_cronograma", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("reporte_locales", "fecha_cierre_cronograma")
    op.drop_column("reporte_locales", "fecha_inicio_cronograma")
