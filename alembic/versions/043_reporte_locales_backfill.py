"""Sincroniza reporte_locales con todos los establishments existentes.

Revision ID: 043_reporte_locales_backfill
Revises: 042_reporte_locales_nota
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "043_reporte_locales_backfill"
down_revision = "042_reporte_locales_nota"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO reporte_locales (
            tenant_id,
            establishment_id,
            situacion,
            fotos_urls,
            pdfs_urls,
            created_at,
            updated_at
        )
        SELECT
            e.tenant_id,
            e.id,
            'pendiente',
            '[]'::jsonb,
            '[]'::jsonb,
            NOW(),
            NOW()
        FROM establishments e
        WHERE NOT EXISTS (
            SELECT 1
            FROM reporte_locales r
            WHERE r.tenant_id = e.tenant_id
              AND r.establishment_id = e.id
        )
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DELETE FROM reporte_locales r
        WHERE r.fecha_inventario_propuesto IS NULL
          AND r.fecha_inventario_real IS NULL
          AND (r.nota IS NULL OR TRIM(r.nota) = '')
          AND r.fotos_urls = '[]'::jsonb
          AND r.pdfs_urls = '[]'::jsonb
          AND r.situacion = 'pendiente'
        """
    )
