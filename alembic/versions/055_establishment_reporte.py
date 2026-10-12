"""reporte en establishments: el reporte Histórico (Margesí) vs Real (Inventario) se activa por local.

Antes se marcaba ambiente por ambiente (``enviroments.reporte``). Ahora un local con ``reporte``
incluye todos sus ambientes, también los que se creen después. Se marca en los locales que ya
tenían algún ambiente con reporte para no perder la configuración actual.

Revision ID: 055_establishment_reporte
Revises: 054_establishment_photos
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "055_establishment_reporte"
down_revision = "054_establishment_photos"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "establishments",
        sa.Column("reporte", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        """
        UPDATE establishments e
        SET reporte = true
        WHERE EXISTS (
            SELECT 1 FROM enviroments env
            WHERE env.establishment_id = e.id
              AND env.tenant_id = e.tenant_id
              AND env.reporte IS TRUE
        )
        """
    )


def downgrade() -> None:
    op.drop_column("establishments", "reporte")
