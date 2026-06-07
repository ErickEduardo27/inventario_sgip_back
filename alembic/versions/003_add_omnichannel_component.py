"""Añade componente IAM omnichannel (chat WhatsApp) y permisos por rol.

Revision ID: 003_add_omnichannel_component
Revises: 002_sync_portal_ui_components
Create Date: 2026-05-02
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "003_add_omnichannel_component"
down_revision = "002_sync_portal_ui_components"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(sa.text("SELECT 1 FROM ui_components WHERE code = 'omnichannel' LIMIT 1")).scalar()
    if exists:
        return

    bind.execute(sa.text("UPDATE ui_components SET order_index = order_index + 1 WHERE order_index >= 9"))

    comp_id = uuid.uuid4()
    bind.execute(
        sa.text(
            """
            INSERT INTO ui_components (
                id, created_at, updated_at, code, name, group_name, route, icon, order_index, is_portal, status
            )
            VALUES (
                :id, now(), now(), 'omnichannel', 'Omnicanal', 'Portal', '/omnicanal', 'Smartphone', 9, false, 'active'
            )
            """
        ),
        {"id": comp_id},
    )

    res = bind.execute(sa.text("SELECT id, code FROM roles WHERE tenant_id IS NULL AND is_deleted = false"))
    role_id_by_code: dict[str, uuid.UUID] = {}
    for row in res:
        role_id_by_code[str(row[1])] = row[0]

    required = ("administrador", "comunicador", "aprobador", "visualizador")
    for code in required:
        if code not in role_id_by_code:
            raise RuntimeError(f"Rol global '{code}' no encontrado; ejecuta migraciones previas.")

    rc = sa.table(
        "role_components",
        sa.column("role_id", postgresql.UUID(as_uuid=True)),
        sa.column("component_id", postgresql.UUID(as_uuid=True)),
        sa.column("can_view", sa.Boolean),
        sa.column("can_create", sa.Boolean),
        sa.column("can_edit", sa.Boolean),
        sa.column("can_delete", sa.Boolean),
        sa.column("can_export", sa.Boolean),
        sa.column("scope", sa.String),
    )

    def perm(role_code: str, *, view: bool, create: bool, edit: bool, delete: bool, export: bool) -> dict:
        return {
            "role_id": role_id_by_code[role_code],
            "component_id": comp_id,
            "can_view": view,
            "can_create": create,
            "can_edit": edit,
            "can_delete": delete,
            "can_export": export,
            "scope": "tenant",
        }

    rows = [
        perm("administrador", view=True, create=True, edit=True, delete=True, export=True),
        perm("comunicador", view=True, create=True, edit=True, delete=False, export=True),
        perm("aprobador", view=True, create=False, edit=True, delete=False, export=False),
        perm("visualizador", view=True, create=False, edit=False, delete=False, export=False),
    ]
    op.bulk_insert(rc, rows)


def downgrade() -> None:
    bind = op.get_bind()
    cid = bind.execute(sa.text("SELECT id FROM ui_components WHERE code = 'omnichannel' LIMIT 1")).scalar()
    if not cid:
        return
    bind.execute(sa.text("DELETE FROM role_components WHERE component_id = :cid"), {"cid": cid})
    bind.execute(sa.text("DELETE FROM ui_components WHERE code = 'omnichannel'"))
    bind.execute(sa.text("UPDATE ui_components SET order_index = order_index - 1 WHERE order_index >= 10"))
