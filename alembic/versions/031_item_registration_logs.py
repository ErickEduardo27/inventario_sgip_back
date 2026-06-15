"""Tabla item_registration_logs para estadísticas de registro de bienes por usuario.

Revision ID: 031_item_registration_logs
Revises: 030_cards_tenant_hoj_num_unique
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "031_item_registration_logs"
down_revision = "030_cards_tenant_hoj_num_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "item_registration_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("itemcard_id", sa.BigInteger(), nullable=False),
        sa.Column("card_id", sa.BigInteger(), nullable=False),
        sa.Column("inv_num", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_item_registration_logs_tenant_id", "item_registration_logs", ["tenant_id"])
    op.create_index("ix_item_registration_logs_user_id", "item_registration_logs", ["user_id"])
    op.create_index("ix_item_registration_logs_itemcard_id", "item_registration_logs", ["itemcard_id"])
    op.create_index("ix_item_reg_log_tenant_user", "item_registration_logs", ["tenant_id", "user_id"])
    op.create_index("ix_item_reg_log_tenant_created", "item_registration_logs", ["tenant_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_item_reg_log_tenant_created", table_name="item_registration_logs")
    op.drop_index("ix_item_reg_log_tenant_user", table_name="item_registration_logs")
    op.drop_index("ix_item_registration_logs_itemcard_id", table_name="item_registration_logs")
    op.drop_index("ix_item_registration_logs_user_id", table_name="item_registration_logs")
    op.drop_index("ix_item_registration_logs_tenant_id", table_name="item_registration_logs")
    op.drop_table("item_registration_logs")
