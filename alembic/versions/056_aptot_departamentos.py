"""Módulo UI: APTOT por departamentos (Reportes).

Registra el módulo en ``ui_components`` para que aparezca en «Permisos por módulo» y copia a cada
perfil los permisos que ya tiene en «APTOT por locales» (mismo tipo de reporte, otro alcance).

Revision ID: 056_aptot_departamentos
Revises: 055_establishment_reporte
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "056_aptot_departamentos"
down_revision = "055_establishment_reporte"
branch_labels = None
depends_on = None

COMPONENT = {
    "code": "reporte_aptot_departamentos",
    "name": "APTOT por departamentos",
    "group_name": "Reportes",
    "route": "/reporte-aptot-departamentos",
    "icon": "Map",
    "order_index": 24,
}
SOURCE_CODE = "reporte_aptot_locales"


def upgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT id FROM ui_components WHERE code = :code"), {"code": COMPONENT["code"]}
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
            COMPONENT,
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
            {"id": str(comp_id), **COMPONENT},
        )

    # Mismos permisos que «APTOT por locales» para cada perfil que aún no tenga el módulo nuevo.
    conn.execute(
        sa.text(
            """
            INSERT INTO role_components
                (role_id, component_id, can_view, can_create, can_edit, can_delete, can_export, scope)
            SELECT rc.role_id, CAST(:cid AS uuid), rc.can_view, rc.can_create, rc.can_edit, rc.can_delete, rc.can_export, rc.scope
            FROM role_components rc
            JOIN ui_components src ON src.id = rc.component_id AND src.code = :source
            WHERE NOT EXISTS (
                SELECT 1 FROM role_components x WHERE x.role_id = rc.role_id AND x.component_id = CAST(:cid AS uuid)
            )
            """
        ),
        {"cid": str(comp_id), "source": SOURCE_CODE},
    )


def downgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT id FROM ui_components WHERE code = :code"), {"code": COMPONENT["code"]}
    ).fetchone()
    if row:
        conn.execute(sa.text("DELETE FROM role_components WHERE component_id = :cid"), {"cid": row[0]})
        conn.execute(sa.text("DELETE FROM ui_components WHERE id = :id"), {"id": row[0]})
