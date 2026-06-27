"""Reporte Locales: campo grupo.

Revision ID: 044_reporte_locales_grupo
Revises: 043_reporte_locales_backfill
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "044_reporte_locales_grupo"
down_revision = "043_reporte_locales_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("reporte_locales", sa.Column("grupo", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("reporte_locales", "grupo")
