"""Tabla user_assigned_bienes: bienes asignados por inventariador (poblado por script SQL).

Revision ID: 032_user_assigned_bienes
Revises: 031_item_registration_logs
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "032_user_assigned_bienes"
down_revision = "031_item_registration_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_assigned_bienes",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("total_bienes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_hojas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_user_assigned_bienes_tenant_user"),
    )
    op.create_index("ix_user_assigned_bienes_tenant_id", "user_assigned_bienes", ["tenant_id"])
    op.create_index("ix_user_assigned_bienes_user_id", "user_assigned_bienes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_user_assigned_bienes_user_id", table_name="user_assigned_bienes")
    op.drop_index("ix_user_assigned_bienes_tenant_id", table_name="user_assigned_bienes")
    op.drop_table("user_assigned_bienes")
