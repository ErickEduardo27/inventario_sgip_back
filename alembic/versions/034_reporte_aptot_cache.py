"""Tabla cache reporte APTOT descarga total + metadatos por tenant.

Revision ID: 034_reporte_aptot_cache
Revises: 033_item_audit_logs
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "034_reporte_aptot_cache"
down_revision = "033_item_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reporte_aptot_cache_meta",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
    )

    op.create_table(
        "reporte_aptot_cache",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_kind", sa.String(length=32), nullable=False),
        sa.Column("source_ref_id", sa.BigInteger(), nullable=False),
        sa.Column("refreshed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("itemcard_id", sa.BigInteger(), nullable=True),
        sa.Column("mar_sit_conta", sa.String(length=50), nullable=True),
        sa.Column("mar_cpat", sa.String(length=200), nullable=True),
        sa.Column("state", sa.String(length=20), nullable=True),
        sa.Column("inv_sit", sa.String(length=20), nullable=True),
        sa.Column("inv_con", sa.String(length=20), nullable=True),
        sa.Column("mar_npri", sa.String(length=100), nullable=True),
        sa.Column("mar_num", sa.String(length=200), nullable=True),
        sa.Column("mar_ccat", sa.String(length=100), nullable=True),
        sa.Column("mar_des", sa.String(length=500), nullable=True),
        sa.Column("mar_esp", sa.String(length=500), nullable=True),
        sa.Column("mar_est", sa.String(length=10), nullable=True),
        sa.Column("mar_uso", sa.String(length=10), nullable=True),
        sa.Column("mar_seg", sa.String(length=10), nullable=True),
        sa.Column("mar_col", sa.String(length=200), nullable=True),
        sa.Column("mar_mar", sa.String(length=200), nullable=True),
        sa.Column("mar_mod", sa.String(length=200), nullable=True),
        sa.Column("mar_tip", sa.String(length=200), nullable=True),
        sa.Column("mar_ser", sa.String(length=200), nullable=True),
        sa.Column("mar_med", sa.String(length=200), nullable=True),
        sa.Column("mar_npla", sa.String(length=100), nullable=True),
        sa.Column("mar_nmot", sa.String(length=100), nullable=True),
        sa.Column("mar_ncha", sa.String(length=100), nullable=True),
        sa.Column("mar_obs", sa.Text(), nullable=True),
        sa.Column("inv_num_1", sa.String(length=100), nullable=True),
        sa.Column("inv_num_2", sa.String(length=100), nullable=True),
        sa.Column("inv_num", sa.String(length=100), nullable=True),
        sa.Column("item_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("item_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("hoj_num", sa.String(length=50), nullable=True),
        sa.Column("hoj_fec", sa.Date(), nullable=True),
        sa.Column("area_code", sa.String(length=100), nullable=True),
        sa.Column("area_description", sa.String(length=200), nullable=True),
        sa.Column("ambiente_code", sa.String(length=100), nullable=True),
        sa.Column("ambiente_description", sa.String(length=500), nullable=True),
        sa.Column("ambiente_piso", sa.String(length=100), nullable=True),
        sa.Column("ambiente_piso_des", sa.String(length=100), nullable=True),
        sa.Column("local_description", sa.String(length=500), nullable=True),
        sa.Column("local_code", sa.String(length=100), nullable=True),
        sa.Column("local_departamento", sa.String(length=200), nullable=True),
        sa.Column("usuario_code", sa.String(length=100), nullable=True),
        sa.Column("usuario", sa.String(length=500), nullable=True),
        sa.Column("fecha_margesi", sa.Date(), nullable=True),
        sa.Column("doc_margesi", sa.String(length=200), nullable=True),
        sa.Column("cuenta_margesi", sa.String(length=100), nullable=True),
        sa.Column("valor_margesi", sa.Numeric(16, 2), nullable=True),
        sa.Column("margesi_sbn", sa.String(length=100), nullable=True),
        sa.Column("margesi_area", sa.String(length=200), nullable=True),
        sa.Column("margesi_departamento", sa.String(length=200), nullable=True),
        sa.Column("margesi_local", sa.String(length=500), nullable=True),
        sa.Column("margesi_ambiente", sa.String(length=500), nullable=True),
        sa.Column("margesi_usuario", sa.String(length=500), nullable=True),
        sa.Column("margesi_description", sa.String(length=500), nullable=True),
        sa.Column("margesi_marca", sa.String(length=200), nullable=True),
        sa.Column("margesi_modelo", sa.String(length=200), nullable=True),
        sa.Column("margesi_tipo", sa.String(length=200), nullable=True),
        sa.Column("margesi_serie", sa.String(length=200), nullable=True),
        sa.Column("margesi_cod_local", sa.String(length=100), nullable=True),
        sa.Column("local_id", sa.BigInteger(), nullable=True),
        sa.Column("margesi_obs", sa.Text(), nullable=True),
        sa.Column("local_libre", sa.String(length=500), nullable=True),
        sa.Column("ccosto_libre", sa.String(length=500), nullable=True),
        sa.Column("ambiente_libre", sa.String(length=500), nullable=True),
        sa.Column("usuario_libre", sa.String(length=500), nullable=True),
        sa.Column("campo_libre", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "source_kind", "source_ref_id", name="uq_reporte_aptot_cache_source"),
    )
    op.create_index("ix_reporte_aptot_cache_tenant", "reporte_aptot_cache", ["tenant_id"])


def downgrade() -> None:
    op.drop_index("ix_reporte_aptot_cache_tenant", table_name="reporte_aptot_cache")
    op.drop_table("reporte_aptot_cache")
    op.drop_table("reporte_aptot_cache_meta")
