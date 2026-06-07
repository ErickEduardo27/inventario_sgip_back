"""Inventario SGIP: módulos UI y perfiles (roles) del sistema.

Revision ID: 027_inventory_profiles
Revises: 026_margesi_extra_text
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "027_inventory_profiles"
down_revision = "026_margesi_extra_text"
branch_labels = None
depends_on = None

INVENTORY_COMPONENTS: list[dict] = [
    {"code": "dashboard", "name": "Dashboard", "group_name": "Inventario", "route": "/", "icon": "LayoutDashboard", "order_index": 1},
    {"code": "locales", "name": "Locales", "group_name": "Inventario", "route": "/locales", "icon": "Building2", "order_index": 2},
    {"code": "locales_mapa", "name": "Mapa de locales", "group_name": "Inventario", "route": "/locales/mapa", "icon": "Globe2", "order_index": 3},
    {"code": "ambientes", "name": "Ambientes", "group_name": "Inventario", "route": "/ambientes", "icon": "MapPin", "order_index": 4},
    {"code": "centro_costo", "name": "Centro de costo", "group_name": "Inventario", "route": "/centro-costo", "icon": "Factory", "order_index": 5},
    {"code": "personas", "name": "Personas", "group_name": "Inventario", "route": "/personas", "icon": "Users", "order_index": 6},
    {"code": "list_sbn", "name": "Catálogo SBN", "group_name": "Inventario", "route": "/list-sbn", "icon": "Tags", "order_index": 7},
    {"code": "margesi", "name": "Patrimonio (Margesi)", "group_name": "Inventario", "route": "/margesi", "icon": "Package", "order_index": 8},
    {"code": "hoja_captura", "name": "Hojas de captura", "group_name": "Operación", "route": "/cards", "icon": "ClipboardList", "order_index": 20},
    {"code": "bienes", "name": "Bienes inventariados", "group_name": "Operación", "route": "/bienes", "icon": "Boxes", "order_index": 21},
    {"code": "conciliacion", "name": "Conciliación", "group_name": "Conciliación", "route": "/conciliacion", "icon": "Link2", "order_index": 30},
    {"code": "conciliacion_sbn", "name": "Conciliación SBN", "group_name": "Conciliación", "route": "/conciliacion-sbn", "icon": "Link2", "order_index": 31},
    {"code": "desconciliacion", "name": "Desconciliación", "group_name": "Conciliación", "route": "/desconciliacion", "icon": "Unlink", "order_index": 32},
    {"code": "desconciliacion_sbn", "name": "Desconciliación SBN", "group_name": "Conciliación", "route": "/desconciliacion-sbn", "icon": "Unlink", "order_index": 33},
    {"code": "no_conciliables", "name": "No conciliables", "group_name": "Conciliación", "route": "/no-conciliables", "icon": "Ban", "order_index": 34},
    {"code": "usuarios", "name": "Usuarios", "group_name": "Administración", "route": "/usuarios", "icon": "UserCog", "order_index": 40},
    {"code": "perfiles", "name": "Perfiles", "group_name": "Administración", "route": "/perfiles", "icon": "Shield", "order_index": 41},
    {"code": "settings", "name": "Entorno y tenant", "group_name": "Administración", "route": "/configuracion", "icon": "Settings", "order_index": 42},
]

SYSTEM_ROLES: list[dict] = [
    {
        "code": "administrador",
        "name": "Administrador",
        "description": "Control total del inventario y administración",
    },
    {
        "code": "inventariador_digitador",
        "name": "Inventariador - digitador",
        "description": "Usuario operativo de captura de bienes",
    },
    {
        "code": "visitante",
        "name": "Visitante",
        "description": "Solo visualización de módulos asignados",
    },
    {
        "code": "supervisor",
        "name": "Supervisor",
        "description": "Inventario, conciliación y reportes",
    },
]

INVENTARIO_CODES = {
    "dashboard", "locales", "locales_mapa", "ambientes", "centro_costo",
    "personas", "list_sbn", "margesi",
}
OPERACION_CODES = {"hoja_captura", "bienes"}
CONCILIACION_CODES = {
    "conciliacion", "conciliacion_sbn", "desconciliacion",
    "desconciliacion_sbn", "no_conciliables",
}
ADMIN_CODES = {"usuarios", "perfiles", "settings"}
ALL_INVENTORY_CODES = INVENTARIO_CODES | OPERACION_CODES | CONCILIACION_CODES | ADMIN_CODES


def _perm(view=False, create=False, edit=False, delete=False, export=False) -> dict:
    return {
        "can_view": view,
        "can_create": create,
        "can_edit": edit,
        "can_delete": delete,
        "can_export": export,
        "scope": "tenant",
    }


def _role_matrix(role_code: str, component_code: str) -> dict | None:
    if role_code == "administrador":
        return _perm(True, True, True, True, True)

    if role_code == "inventariador_digitador":
        if component_code in INVENTARIO_CODES:
            return _perm(True, False, False, False, False)
        if component_code == "hoja_captura":
            return _perm(True, True, True, True, False)
        if component_code == "bienes":
            return _perm(True, False, False, False, False)
        return None

    if role_code == "visitante":
        if component_code in ALL_INVENTORY_CODES - ADMIN_CODES:
            return _perm(True, False, False, False, False)
        return None

    if role_code == "supervisor":
        if component_code in INVENTARIO_CODES:
            return _perm(True, True, True, False, True)
        if component_code in OPERACION_CODES:
            return _perm(True, True, True, False, True)
        if component_code in CONCILIACION_CODES:
            return _perm(True, True, True, True, True)
        return None

    return None


def upgrade() -> None:
    conn = op.get_bind()

    for comp in INVENTORY_COMPONENTS:
        row = conn.execute(
            sa.text("SELECT id FROM ui_components WHERE code = :code"),
            {"code": comp["code"]},
        ).fetchone()
        if row:
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
            conn.execute(
                sa.text(
                    """
                    INSERT INTO ui_components
                        (id, code, name, group_name, route, icon, order_index, is_portal, status)
                    VALUES
                        (:id, :code, :name, :group_name, :route, :icon, :order_index, false, 'active')
                    """
                ),
                {"id": str(uuid.uuid4()), **comp},
            )

    comp_ids = {
        r[0]: r[1]
        for r in conn.execute(sa.text("SELECT code, id FROM ui_components")).fetchall()
    }

    role_ids: dict[str, uuid.UUID] = {}
    for role in SYSTEM_ROLES:
        row = conn.execute(
            sa.text(
                "SELECT id FROM roles WHERE tenant_id IS NULL AND code = :code AND is_deleted = false"
            ),
            {"code": role["code"]},
        ).fetchone()
        if row:
            role_id = row[0]
            conn.execute(
                sa.text(
                    """
                    UPDATE roles SET name = :name, description = :description, is_system = true
                    WHERE id = :id
                    """
                ),
                {"id": role_id, "name": role["name"], "description": role["description"]},
            )
        else:
            role_id = uuid.uuid4()
            conn.execute(
                sa.text(
                    """
                    INSERT INTO roles (id, tenant_id, name, code, description, is_system, is_deleted)
                    VALUES (:id, NULL, :name, :code, :description, true, false)
                    """
                ),
                {"id": role_id, **role},
            )
        role_ids[role["code"]] = role_id

    for role_code, role_id in role_ids.items():
        for comp_code in ALL_INVENTORY_CODES:
            if comp_code not in comp_ids:
                continue
            perms = _role_matrix(role_code, comp_code)
            if not perms:
                conn.execute(
                    sa.text(
                        "DELETE FROM role_components WHERE role_id = :rid AND component_id = :cid"
                    ),
                    {"rid": role_id, "cid": comp_ids[comp_code]},
                )
                continue
            existing = conn.execute(
                sa.text(
                    "SELECT 1 FROM role_components WHERE role_id = :rid AND component_id = :cid"
                ),
                {"rid": role_id, "cid": comp_ids[comp_code]},
            ).fetchone()
            if existing:
                conn.execute(
                    sa.text(
                        """
                        UPDATE role_components
                        SET can_view = :can_view, can_create = :can_create, can_edit = :can_edit,
                            can_delete = :can_delete, can_export = :can_export, scope = :scope
                        WHERE role_id = :rid AND component_id = :cid
                        """
                    ),
                    {"rid": role_id, "cid": comp_ids[comp_code], **perms},
                )
            else:
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO role_components
                            (role_id, component_id, can_view, can_create, can_edit, can_delete, can_export, scope)
                        VALUES
                            (:rid, :cid, :can_view, :can_create, :can_edit, :can_delete, :can_export, :scope)
                        """
                    ),
                    {"rid": role_id, "cid": comp_ids[comp_code], **perms},
                )


def downgrade() -> None:
    conn = op.get_bind()
    codes = [c["code"] for c in INVENTORY_COMPONENTS if c["code"] not in ("dashboard", "usuarios", "settings")]
    for code in codes:
        conn.execute(sa.text("DELETE FROM ui_components WHERE code = :code"), {"code": code})
    for role in ("inventariador_digitador", "visitante", "supervisor"):
        conn.execute(
            sa.text("DELETE FROM roles WHERE tenant_id IS NULL AND code = :code"),
            {"code": role},
        )
