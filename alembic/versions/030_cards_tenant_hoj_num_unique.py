"""Índice único tenant + hoj_num para upsert masivo de hojas de captura.

Revision ID: 030_cards_tenant_hoj_num_unique
Revises: 029_import_jobs
"""

from __future__ import annotations

from alembic import op

revision = "030_cards_tenant_hoj_num_unique"
down_revision = "029_import_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_cards_tenant_hoj_num
        ON cards (tenant_id, hoj_num)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_cards_tenant_hoj_num")
