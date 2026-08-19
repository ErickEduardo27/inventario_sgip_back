"""Migración: tablas de asistencia + módulos UI asistencia y panel_asistencia."""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op

revision = "048_attendance_module"
down_revision = "047_reporte_aptot_locales_module"
branch_labels = None
depends_on = None

UI_COMPONENTS = (
    {
        "code": "asistencia",
        "name": "Asistencia",
        "group_name": "Operación",
        "route": "/asistencia",
        "icon": "MapPinned",
        "order_index": 12,
    },
    {
        "code": "panel_asistencia",
        "name": "Panel de asistencia",
        "group_name": "Operación",
        "route": "/panel-asistencia",
        "icon": "LayoutDashboard",
        "order_index": 13,
    },
)

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


def _role_matrix(component_code: str, role_code: str) -> dict | None:
    if component_code == "asistencia":
        if role_code in ("administrador", "inventariador_digitador", "supervisor"):
            return _perm(True, True, False, False, False)
        if role_code == "visitante":
            return _perm(True, False, False, False, False)
        return None
    if component_code == "panel_asistencia":
        if role_code in ("administrador", "supervisor"):
            return _perm(True, True, True, False, True)
        if role_code == "inventariador_digitador":
            return _perm(True, False, False, False, False)
        return None
    return None


def upgrade() -> None:
    op.add_column(
        "establishments",
        sa.Column("geofence_radius_m", sa.Integer(), nullable=False, server_default="100"),
    )

    op.create_table(
        "user_establishment_assignments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("establishment_id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["establishment_id"], ["establishments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "user_id", "establishment_id", name="uq_user_est_assignment"),
    )
    op.create_index("ix_user_est_assignment_user", "user_establishment_assignments", ["tenant_id", "user_id"])

    op.create_table(
        "attendance_sessions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("establishment_id", sa.BigInteger(), nullable=False),
        sa.Column("work_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="abierta"),
        sa.Column("inventory_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["establishment_id"], ["establishments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "establishment_id",
            "work_date",
            name="uq_attendance_session_day",
        ),
    )
    op.create_index("ix_attendance_session_tenant_date", "attendance_sessions", ["tenant_id", "work_date"])

    op.create_table(
        "attendance_marks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("establishment_id", sa.BigInteger(), nullable=False),
        sa.Column("mark_type", sa.String(length=32), nullable=False),
        sa.Column("marked_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("distance_m", sa.Float(), nullable=True),
        sa.Column("geofence_valid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="PRESENTE"),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("device_info", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["session_id"], ["attendance_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attendance_marks_session", "attendance_marks", ["session_id", "marked_at"])

    op.create_table(
        "attendance_location_samples",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("session_id", sa.BigInteger(), nullable=False),
        sa.Column("latitude", sa.Float(), nullable=False),
        sa.Column("longitude", sa.Float(), nullable=False),
        sa.Column("accuracy_m", sa.Float(), nullable=True),
        sa.Column("sampled_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["attendance_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_attendance_loc_sample_session", "attendance_location_samples", ["session_id", "sampled_at"])

    conn = op.get_bind()
    for comp in UI_COMPONENTS:
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
            perms = _role_matrix(comp["code"], role_code)
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
    for comp in UI_COMPONENTS:
        comp_row = conn.execute(
            sa.text("SELECT id FROM ui_components WHERE code = :code"),
            {"code": comp["code"]},
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

    op.drop_index("ix_attendance_loc_sample_session", table_name="attendance_location_samples")
    op.drop_table("attendance_location_samples")
    op.drop_index("ix_attendance_marks_session", table_name="attendance_marks")
    op.drop_table("attendance_marks")
    op.drop_index("ix_attendance_session_tenant_date", table_name="attendance_sessions")
    op.drop_table("attendance_sessions")
    op.drop_index("ix_user_est_assignment_user", table_name="user_establishment_assignments")
    op.drop_table("user_establishment_assignments")
    op.drop_column("establishments", "geofence_radius_m")
