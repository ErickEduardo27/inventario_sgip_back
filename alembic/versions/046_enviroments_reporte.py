"""Ambientes: campo reporte (sí/no).

Revision ID: 046_enviroments_reporte
Revises: 045_reporte_locales_cronograma
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "046_enviroments_reporte"
down_revision = "045_reporte_locales_cronograma"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "enviroments",
        sa.Column("reporte", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("enviroments", "reporte")
