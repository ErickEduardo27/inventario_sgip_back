"""Índices únicos para upsert masivo en importaciones (COPY + staging).

Revision ID: 028_import_unique_indexes
Revises: 027_inventory_profiles
"""

from __future__ import annotations

from alembic import op

revision = "028_import_unique_indexes"
down_revision = "027_inventory_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_enviroments_tenant_code
        ON enviroments (tenant_id, code)
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_margesi_tenant_mar_num
        ON margesi (tenant_id, mar_num)
        WHERE mar_num IS NOT NULL AND TRIM(mar_num) <> ''
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_persons_tenant_codigo_interno
        ON persons (tenant_id, ((extra->>'codigo_interno')))
        WHERE extra->>'codigo_interno' IS NOT NULL AND TRIM(extra->>'codigo_interno') <> ''
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_persons_tenant_codigo_interno")
    op.execute("DROP INDEX IF EXISTS uq_margesi_tenant_mar_num")
    op.execute("DROP INDEX IF EXISTS uq_enviroments_tenant_code")
