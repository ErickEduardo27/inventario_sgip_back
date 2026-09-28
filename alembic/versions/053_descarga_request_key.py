"""request_key en descarga_archivos para reutilizar exportaciones idénticas.

Revision ID: 053_descarga_request_key
Revises: 052_conciliacion_margesi_module
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "053_descarga_request_key"
down_revision = "052_conciliacion_margesi_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "descarga_archivos",
        sa.Column("request_key", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_descarga_archivos_tenant_module_request_key",
        "descarga_archivos",
        ["tenant_id", "module", "request_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_descarga_archivos_tenant_module_request_key", table_name="descarga_archivos")
    op.drop_column("descarga_archivos", "request_key")
