"""Reporte Locales: seguimiento por local + módulo UI.

Revision ID: 040_reporte_locales
Revises: 039_establishment_stats
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "040_reporte_locales"
down_revision = "039_establishment_stats"
branch_labels = None
depends_on = None

REPORTE_LOCALES_COMPONENT = {
    "code": "reporte_locales",
    "name": "Reporte Locales",
    "group_name": "Reportes",
    "route": "/reporte-locales",
    "icon": "Building2",
    "order_index": 23,
}

SYSTEM_ROLE_CODES = ("administrador", "inventariador_digitador", "visitante", "supervisor")


def _perm(view=False, create=False, edit=False, delete=False, export=False) -> dict:
    return {
        "can_view": view,
        "can_create": create,
        "can_edit": edit,
        "can_delete": delete,
        "can_export": export,
        "scope": "tenant",
    }


def _role_matrix(role_code: str) -> dict | None:
    if role_code == "administrador":
        return _perm(True, False, True, False, False)
    if role_code == "supervisor":
        return _perm(True, False, True, False, False)
    if role_code in ("inventariador_digitador", "visitante"):
        return _perm(True, False, False, False, False)
    return None


def upgrade() -> None:
    op.create_table(
        "reporte_locales",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("establishment_id", sa.BigInteger(), nullable=False),
        sa.Column("fecha_inventario_propuesto", sa.Date(), nullable=True),
        sa.Column("fecha_inventario_real", sa.Date(), nullable=True),
        sa.Column("carga_fotos", sa.String(length=500), nullable=True),
        sa.Column("carga_documentos_pdf", sa.String(length=500), nullable=True),
        sa.Column(
            "situacion",
            sa.String(length=32),
            nullable=False,
            server_default="pendiente",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["establishment_id"], ["establishments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "establishment_id", name="uq_reporte_locales_tenant_est"),
    )
    op.create_index("ix_reporte_locales_tenant", "reporte_locales", ["tenant_id"])

    conn = op.get_bind()
    comp = REPORTE_LOCALES_COMPONENT
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
        perms = _role_matrix(role_code)
        if perms is None:
            continue
        role_row = conn.execute(
            sa.text(
                "SELECT id FROM roles WHERE tenant_id IS NULL AND code = :code AND is_deleted = false"
            ),
            {"code": role_code},
        ).fetchone()
        if not role_row:
            continue
        role_id = role_row[0]
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
                    SET can_view = :can_view, can_create = :can_create, can_edit = :can_edit,
                        can_delete = :can_delete, can_export = :can_export, scope = :scope
                    WHERE role_id = :rid AND component_id = :cid
                    """
                ),
                {"rid": role_id, "cid": comp_id, **perms},
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
                {"rid": role_id, "cid": comp_id, **perms},
            )


def downgrade() -> None:
    conn = op.get_bind()
    comp_row = conn.execute(
        sa.text("SELECT id FROM ui_components WHERE code = :code"),
        {"code": REPORTE_LOCALES_COMPONENT["code"]},
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
    op.drop_index("ix_reporte_locales_tenant", table_name="reporte_locales")
    op.drop_table("reporte_locales")
