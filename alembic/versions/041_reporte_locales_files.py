"""Reporte Locales: columnas JSON para URLs de fotos y PDF en GCS.

Revision ID: 041_reporte_locales_files
Revises: 040_reporte_locales
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "041_reporte_locales_files"
down_revision = "040_reporte_locales"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "reporte_locales",
        sa.Column("fotos_urls", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.add_column(
        "reporte_locales",
        sa.Column("pdfs_urls", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )
    op.drop_column("reporte_locales", "carga_fotos")
    op.drop_column("reporte_locales", "carga_documentos_pdf")


def downgrade() -> None:
    op.add_column("reporte_locales", sa.Column("carga_fotos", sa.String(length=500), nullable=True))
    op.add_column("reporte_locales", sa.Column("carga_documentos_pdf", sa.String(length=500), nullable=True))
    op.drop_column("reporte_locales", "fotos_urls")
    op.drop_column("reporte_locales", "pdfs_urls")
