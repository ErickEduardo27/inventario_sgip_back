"""Cache materializado: resumen dashboard por local (Margesi + inventario).

Revision ID: 039_establishment_stats
Revises: 038_imagenes_module
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "039_establishment_stats"
down_revision = "038_imagenes_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_establishment_stats",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("establishment_id", sa.BigInteger(), nullable=False),
        sa.Column("establishment_code", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("establishment_description", sa.String(length=500), nullable=True),
        sa.Column("margesi_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("margesi_conciliado", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("margesi_faltantes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("margesi_no_inventariable", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inventario_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inventario_conciliado", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inventario_sobrante", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inventario_no_conciliable", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["establishment_id"], ["establishments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "establishment_id", name="uq_dashboard_est_stats_tenant_est"),
    )
    op.create_index(
        "ix_dashboard_est_stats_tenant",
        "dashboard_establishment_stats",
        ["tenant_id"],
    )
    op.create_index(
        "ix_dashboard_est_stats_tenant_code",
        "dashboard_establishment_stats",
        ["tenant_id", "establishment_code"],
    )


def downgrade() -> None:
    op.drop_index("ix_dashboard_est_stats_tenant_code", table_name="dashboard_establishment_stats")
    op.drop_index("ix_dashboard_est_stats_tenant", table_name="dashboard_establishment_stats")
    op.drop_table("dashboard_establishment_stats")
