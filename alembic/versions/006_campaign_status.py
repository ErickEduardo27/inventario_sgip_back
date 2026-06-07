"""Normaliza estado de campaña a activo / inactivo.

Revision ID: 006_campaign_status
Revises: 005_business_model_core
Create Date: 2026-05-03
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "006_campaign_status"
down_revision = "005_business_model_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        text(
            """
            UPDATE campaigns
            SET status = 'inactivo'
            WHERE status IN ('cancelada', 'fallida');
            """
        )
    )
    bind.execute(
        text(
            """
            UPDATE campaigns
            SET status = 'activo'
            WHERE status NOT IN ('activo', 'inactivo');
            """
        )
    )


def downgrade() -> None:
    pass
