"""Reset catálogo ui_components y matriz role_components al portal Conectados Directo.

Corrige instalaciones que conservan componentes del proyecto anterior en `ui_components`.

Revision ID: 002_sync_portal_ui_components
Revises: 001_initial_schema
Create Date: 2026-05-02
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "002_sync_portal_ui_components"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(sa.text("DELETE FROM role_components"))
    bind.execute(sa.text("DELETE FROM ui_components"))

    components_table = sa.table(
        "ui_components",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("group_name", sa.String),
        sa.column("route", sa.String),
        sa.column("icon", sa.String),
        sa.column("order_index", sa.Integer),
        sa.column("is_portal", sa.Boolean),
        sa.column("status", sa.String),
    )

    components_seed: list[dict] = [
        {
            "id": uuid.uuid4(),
            "code": "dashboard",
            "name": "Dashboard",
            "group_name": "Portal",
            "route": "/",
            "icon": "LayoutDashboard",
            "order_index": 1,
            "is_portal": False,
            "status": "active",
        },
        {
            "id": uuid.uuid4(),
            "code": "campaigns",
            "name": "Campañas",
            "group_name": "Portal",
            "route": "/campanas",
            "icon": "Megaphone",
            "order_index": 2,
            "is_portal": False,
            "status": "active",
        },
        {
            "id": uuid.uuid4(),
            "code": "scheduled_messages",
            "name": "Mensajes programados",
            "group_name": "Portal",
            "route": "/mensajes-programados",
            "icon": "CalendarClock",
            "order_index": 3,
            "is_portal": False,
            "status": "active",
        },
        {
            "id": uuid.uuid4(),
            "code": "contacts",
            "name": "Contactos",
            "group_name": "Portal",
            "route": "/contactos",
            "icon": "Users",
            "order_index": 4,
            "is_portal": False,
            "status": "active",
        },
        {
            "id": uuid.uuid4(),
            "code": "segments",
            "name": "Segmentos",
            "group_name": "Portal",
            "route": "/segmentos",
            "icon": "Layers",
            "order_index": 5,
            "is_portal": False,
            "status": "active",
        },
        {
            "id": uuid.uuid4(),
            "code": "templates",
            "name": "Plantillas",
            "group_name": "Portal",
            "route": "/plantillas",
            "icon": "MessageSquare",
            "order_index": 6,
            "is_portal": False,
            "status": "active",
        },
        {
            "id": uuid.uuid4(),
            "code": "surveys",
            "name": "Encuestas",
            "group_name": "Portal",
            "route": "/encuestas",
            "icon": "ClipboardList",
            "order_index": 7,
            "is_portal": False,
            "status": "active",
        },
        {
            "id": uuid.uuid4(),
            "code": "reports",
            "name": "Reportes",
            "group_name": "Portal",
            "route": "/reportes",
            "icon": "BarChart3",
            "order_index": 8,
            "is_portal": False,
            "status": "active",
        },
        {
            "id": uuid.uuid4(),
            "code": "omnichannel",
            "name": "Omnicanal",
            "group_name": "Portal",
            "route": "/omnicanal",
            "icon": "Smartphone",
            "order_index": 9,
            "is_portal": False,
            "status": "active",
        },
        {
            "id": uuid.uuid4(),
            "code": "users",
            "name": "Usuarios",
            "group_name": "Administración",
            "route": "/usuarios",
            "icon": "UserCog",
            "order_index": 10,
            "is_portal": False,
            "status": "active",
        },
        {
            "id": uuid.uuid4(),
            "code": "settings",
            "name": "Configuración",
            "group_name": "Administración",
            "route": "/configuracion",
            "icon": "Settings",
            "order_index": 11,
            "is_portal": False,
            "status": "active",
        },
    ]
    op.bulk_insert(components_table, components_seed)
    component_id_by_code = {c["code"]: c["id"] for c in components_seed}

    res = bind.execute(
        sa.text(
            "SELECT id, code FROM roles WHERE tenant_id IS NULL AND is_deleted = false"
        )
    )
    role_id_by_code: dict[str, uuid.UUID] = {}
    for row in res:
        role_id_by_code[str(row[1])] = row[0]

    required_roles = ("administrador", "comunicador", "aprobador", "visualizador")
    missing = [c for c in required_roles if c not in role_id_by_code]
    if missing:
        raise RuntimeError(
            "Faltan roles globales en la base de datos: "
            + ", ".join(missing)
            + ". Ejecuta la migración 001 o crea los roles antes."
        )

    role_components_table = sa.table(
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

    def _row(role_code: str, component_code: str, *, view=True, create=False, edit=False, delete=False, export=False) -> dict:
        return {
            "role_id": role_id_by_code[role_code],
            "component_id": component_id_by_code[component_code],
            "can_view": view,
            "can_create": create,
            "can_edit": edit,
            "can_delete": delete,
            "can_export": export,
            "scope": "tenant",
        }

    rc_rows: list[dict] = []

    for code in component_id_by_code.keys():
        rc_rows.append(_row("administrador", code, view=True, create=True, edit=True, delete=True, export=True))

    comunicador_full = [
        "dashboard",
        "campaigns",
        "scheduled_messages",
        "contacts",
        "segments",
        "templates",
        "surveys",
        "reports",
        "omnichannel",
    ]
    for code in comunicador_full:
        rc_rows.append(_row("comunicador", code, view=True, create=True, edit=True, delete=False, export=True))

    aprobador_view_edit = ["dashboard", "campaigns", "scheduled_messages", "reports", "omnichannel"]
    for code in aprobador_view_edit:
        rc_rows.append(_row("aprobador", code, view=True, create=False, edit=True, delete=False, export=True))

    for code in ("dashboard", "reports", "omnichannel"):
        rc_rows.append(_row("visualizador", code, view=True, create=False, edit=False, delete=False, export=True))

    op.bulk_insert(role_components_table, rc_rows)


def downgrade() -> None:
    """No revierte el reset de datos; la migración es una corrección idempotente del catálogo."""
    pass
