"""Tabla descarga_archivos para exportaciones CSV asíncronas (GCS + Celery).

Revision ID: 037_descarga_archivos
Revises: 036_invnum_bigint
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "037_descarga_archivos"
down_revision = "036_invnum_bigint"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "descarga_archivos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("gcs_path", sa.String(length=1000), nullable=True),
        sa.Column("download_url", sa.Text(), nullable=True),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_descarga_archivos_tenant_id", "descarga_archivos", ["tenant_id"])
    op.create_index("ix_descarga_archivos_module", "descarga_archivos", ["module"])
    op.create_index("ix_descarga_archivos_state", "descarga_archivos", ["state"])
    op.create_index("ix_descarga_archivos_celery_task_id", "descarga_archivos", ["celery_task_id"])
    op.create_index("ix_descarga_archivos_created_by_id", "descarga_archivos", ["created_by_id"])


def downgrade() -> None:
    op.drop_index("ix_descarga_archivos_created_by_id", table_name="descarga_archivos")
    op.drop_index("ix_descarga_archivos_celery_task_id", table_name="descarga_archivos")
    op.drop_index("ix_descarga_archivos_state", table_name="descarga_archivos")
    op.drop_index("ix_descarga_archivos_module", table_name="descarga_archivos")
    op.drop_index("ix_descarga_archivos_tenant_id", table_name="descarga_archivos")
    op.drop_table("descarga_archivos")
