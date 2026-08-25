"""Migración: logo de PDF independiente del logo del portal."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "050_pdf_logo"
down_revision = "049_tenant_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspace_settings", sa.Column("pdf_logo_url", sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace_settings", "pdf_logo_url")
