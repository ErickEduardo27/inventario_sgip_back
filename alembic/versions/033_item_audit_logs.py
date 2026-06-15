"""Tabla item_audit_logs y módulo UI auditoría (visible en todos los perfiles).

Revision ID: 033_item_audit_logs
Revises: 032_user_assigned_bienes
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "033_item_audit_logs"
down_revision = "032_user_assigned_bienes"
branch_labels = None
depends_on = None

AUDITORIA_COMPONENT = {
    "code": "auditoria",
    "name": "Auditoría",
    "group_name": "Administración",
    "route": "/auditoria",
    "icon": "ScrollText",
    "order_index": 43,
}

SYSTEM_ROLE_CODES = ("administrador", "inventariador_digitador", "visitante", "supervisor")


def upgrade() -> None:
    op.create_table(
        "item_audit_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=20), nullable=False),
        sa.Column("itemcard_id", sa.BigInteger(), nullable=True),
        sa.Column("card_id", sa.BigInteger(), nullable=False),
        sa.Column("inv_num", sa.String(length=100), nullable=True),
        sa.Column("mar_des", sa.String(length=500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_item_audit_logs_tenant_id", "item_audit_logs", ["tenant_id"])
    op.create_index("ix_item_audit_logs_user_id", "item_audit_logs", ["user_id"])
    op.create_index("ix_item_audit_logs_action", "item_audit_logs", ["action"])
    op.create_index("ix_item_audit_logs_itemcard_id", "item_audit_logs", ["itemcard_id"])
    op.create_index("ix_item_audit_logs_inv_num", "item_audit_logs", ["inv_num"])
    op.create_index("ix_item_audit_log_tenant_created", "item_audit_logs", ["tenant_id", "created_at"])
    op.create_index("ix_item_audit_log_tenant_action", "item_audit_logs", ["tenant_id", "action"])
    op.create_index("ix_item_audit_log_tenant_user", "item_audit_logs", ["tenant_id", "user_id"])

    conn = op.get_bind()
    comp = AUDITORIA_COMPONENT
    row = conn.execute(
        sa.text("SELECT id FROM ui_components WHERE code = :code"),
        {"code": comp["code"]},
    ).fetchone()
    if row:
        comp_id = row[0]
        conn.execute(
            sa.text(
                """
                UPDATE ui_components
                SET name = :name, group_name = :group_name, route = :route,
                    icon = :icon, order_index = :order_index, status = 'active'
                WHERE code = :code
                """
            ),
            comp,
        )
    else:
        comp_id = uuid.uuid4()
        conn.execute(
            sa.text(
                """
                INSERT INTO ui_components
                    (id, code, name, group_name, route, icon, order_index, is_portal, status)
                VALUES
                    (:id, :code, :name, :group_name, :route, :icon, :order_index, false, 'active')
                """
            ),
            {"id": str(comp_id), **comp},
        )

    for role_code in SYSTEM_ROLE_CODES:
        role_row = conn.execute(
            sa.text(
                "SELECT id FROM roles WHERE tenant_id IS NULL AND code = :code AND is_deleted = false"
            ),
            {"code": role_code},
        ).fetchone()
        if not role_row:
            continue
        role_id = role_row[0]
        can_export = role_code in ("administrador", "supervisor")
        existing = conn.execute(
            sa.text(
                "SELECT 1 FROM role_components WHERE role_id = :rid AND component_id = :cid"
            ),
            {"rid": role_id, "cid": comp_id},
        ).fetchone()
        if existing:
            conn.execute(
                sa.text(
                    """
                    UPDATE role_components
                    SET can_view = true, can_create = false, can_edit = false,
                        can_delete = false, can_export = :can_export, scope = 'tenant'
                    WHERE role_id = :rid AND component_id = :cid
                    """
                ),
                {"rid": role_id, "cid": comp_id, "can_export": can_export},
            )
        else:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO role_components
                        (role_id, component_id, can_view, can_create, can_edit, can_delete, can_export, scope)
                    VALUES
                        (:rid, :cid, true, false, false, false, :can_export, 'tenant')
                    """
                ),
                {"rid": role_id, "cid": comp_id, "can_export": can_export},
            )


def downgrade() -> None:
    conn = op.get_bind()
    comp_row = conn.execute(
        sa.text("SELECT id FROM ui_components WHERE code = :code"),
        {"code": AUDITORIA_COMPONENT["code"]},
    ).fetchone()
    if comp_row:
        conn.execute(
            sa.text("DELETE FROM role_components WHERE component_id = :cid"),
            {"cid": comp_row[0]},
        )
        conn.execute(
            sa.text("DELETE FROM ui_components WHERE id = :id"),
            {"id": comp_row[0]},
        )

    op.drop_index("ix_item_audit_log_tenant_user", table_name="item_audit_logs")
    op.drop_index("ix_item_audit_log_tenant_action", table_name="item_audit_logs")
    op.drop_index("ix_item_audit_log_tenant_created", table_name="item_audit_logs")
    op.drop_index("ix_item_audit_logs_inv_num", table_name="item_audit_logs")
    op.drop_index("ix_item_audit_logs_itemcard_id", table_name="item_audit_logs")
    op.drop_index("ix_item_audit_logs_action", table_name="item_audit_logs")
    op.drop_index("ix_item_audit_logs_user_id", table_name="item_audit_logs")
    op.drop_index("ix_item_audit_logs_tenant_id", table_name="item_audit_logs")
    op.drop_table("item_audit_logs")
