"""initial schema for Conectados Directo (WhatsApp Masivo)

Revision ID: 001_initial_schema
Revises: None
Create Date: 2026-05-02
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("plan_code", sa.String(length=50), nullable=False, server_default="enterprise"),
        sa.Column("timezone", sa.String(length=100), nullable=False, server_default="America/Lima"),
        sa.Column("locale", sa.String(length=20), nullable=False, server_default="es-PE"),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="PEN"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(op.f("ix_tenants_slug"), "tenants", ["slug"])

    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "code", name="uq_roles_tenant_code"),
    )
    op.create_index(op.f("ix_roles_tenant_id"), "roles", ["tenant_id"])

    op.create_table(
        "ui_components",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("code", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("group_name", sa.String(length=100), nullable=False),
        sa.Column("route", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("icon", sa.String(length=100), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_portal", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    op.create_index(op.f("ix_ui_components_code"), "ui_components", ["code"])

    op.create_table(
        "role_components",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("component_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("can_view", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("can_create", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("can_edit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("can_delete", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("can_export", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("scope", sa.String(length=20), nullable=False, server_default="tenant"),
        sa.ForeignKeyConstraint(["component_id"], ["ui_components.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "component_id"),
    )

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False),
        sa.Column("email", sa.String(length=200), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=50), nullable=False, server_default="active"),
        sa.Column("last_access_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_superadmin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index(op.f("ix_users_tenant_id"), "users", ["tenant_id"])
    op.create_index(op.f("ix_users_email"), "users", ["email"])

    op.create_table(
        "user_roles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "role_id"),
    )

    op.create_table(
        "contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("first_name", sa.String(length=150), nullable=False),
        sa.Column("last_name", sa.String(length=150), nullable=False, server_default=""),
        sa.Column("whatsapp_number", sa.String(length=50), nullable=False),
        sa.Column("document", sa.String(length=50), nullable=True),
        sa.Column("area", sa.String(length=120), nullable=True),
        sa.Column("site", sa.String(length=120), nullable=True),
        sa.Column("position", sa.String(length=150), nullable=True),
        sa.Column("region", sa.String(length=120), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="activo"),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "whatsapp_number", name="uq_contacts_tenant_whatsapp"),
    )
    op.create_index(op.f("ix_contacts_tenant_id"), "contacts", ["tenant_id"])
    op.create_index(op.f("ix_contacts_whatsapp_number"), "contacts", ["whatsapp_number"])
    op.create_index(op.f("ix_contacts_area"), "contacts", ["area"])
    op.create_index(op.f("ix_contacts_site"), "contacts", ["site"])
    op.create_index(op.f("ix_contacts_position"), "contacts", ["position"])
    op.create_index(op.f("ix_contacts_region"), "contacts", ["region"])
    op.create_index(op.f("ix_contacts_status"), "contacts", ["status"])

    op.create_table(
        "segments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("criteria", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="activo"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_segments_tenant_name"),
    )
    op.create_index(op.f("ix_segments_tenant_id"), "segments", ["tenant_id"])

    op.create_table(
        "message_templates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=60), nullable=False, server_default="comunicado"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("variables", postgresql.ARRAY(sa.String(length=60)), nullable=False, server_default=sa.text("'{}'::varchar[]")),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="activo"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_templates_tenant_name"),
    )
    op.create_index(op.f("ix_message_templates_tenant_id"), "message_templates", ["tenant_id"])
    op.create_index(op.f("ix_message_templates_category"), "message_templates", ["category"])

    op.create_table(
        "campaigns",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("campaign_type", sa.String(length=60), nullable=False, server_default="comunicado"),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="borrador"),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("custom_message", sa.Text(), nullable=True),
        sa.Column("scheduled_date", sa.Date(), nullable=True),
        sa.Column("scheduled_time", sa.Time(), nullable=True),
        sa.Column("attachment_filename", sa.String(length=200), nullable=True),
        sa.Column("contacts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("delivered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("read_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("response_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["template_id"], ["message_templates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_campaigns_tenant_id"), "campaigns", ["tenant_id"])
    op.create_index(op.f("ix_campaigns_name"), "campaigns", ["name"])
    op.create_index(op.f("ix_campaigns_campaign_type"), "campaigns", ["campaign_type"])
    op.create_index(op.f("ix_campaigns_status"), "campaigns", ["status"])
    op.create_index(op.f("ix_campaigns_segment_id"), "campaigns", ["segment_id"])
    op.create_index(op.f("ix_campaigns_template_id"), "campaigns", ["template_id"])
    op.create_index(op.f("ix_campaigns_scheduled_date"), "campaigns", ["scheduled_date"])
    op.create_index(op.f("ix_campaigns_created_by_user_id"), "campaigns", ["created_by_user_id"])

    op.create_table(
        "surveys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("response_type", sa.String(length=40), nullable=False, server_default="si_no"),
        sa.Column("options", postgresql.ARRAY(sa.String(length=200)), nullable=False, server_default=sa.text("'{}'::varchar[]")),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="activo"),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("response_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_surveys_tenant_id"), "surveys", ["tenant_id"])
    op.create_index(op.f("ix_surveys_name"), "surveys", ["name"])
    op.create_index(op.f("ix_surveys_campaign_id"), "surveys", ["campaign_id"])
    op.create_index(op.f("ix_surveys_segment_id"), "surveys", ["segment_id"])

    op.create_table(
        "workspace_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("business_sector", sa.String(length=120), nullable=True),
        sa.Column("whatsapp_number", sa.String(length=50), nullable=True),
        sa.Column("whatsapp_display_name", sa.String(length=200), nullable=True),
        sa.Column("connection_status", sa.String(length=40), nullable=False, server_default="pendiente"),
        sa.Column("cost_per_message", sa.Numeric(precision=10, scale=4), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=10), nullable=False, server_default="PEN"),
        sa.Column("timezone", sa.String(length=80), nullable=False, server_default="America/Lima"),
        sa.Column("logo_url", sa.String(length=500), nullable=True),
        sa.Column("google_cloud_info", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("alerts_config", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("portal_branding", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("integration_notes", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", name="uq_workspace_settings_tenant"),
    )
    op.create_index(op.f("ix_workspace_settings_tenant_id"), "workspace_settings", ["tenant_id"])

    _seed_roles_and_components()


def _seed_roles_and_components() -> None:
    """Inserta roles globales y componentes UI con su matriz de permisos."""
    bind = op.get_bind()

    roles_table = sa.table(
        "roles",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("tenant_id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("code", sa.String),
        sa.column("description", sa.String),
        sa.column("is_system", sa.Boolean),
    )

    roles_seed: list[dict] = [
        {
            "id": uuid.uuid4(),
            "tenant_id": None,
            "name": "Administrador",
            "code": "administrador",
            "description": "Acceso total al portal",
            "is_system": True,
        },
        {
            "id": uuid.uuid4(),
            "tenant_id": None,
            "name": "Comunicador",
            "code": "comunicador",
            "description": "Crea campañas, contactos, plantillas y encuestas",
            "is_system": True,
        },
        {
            "id": uuid.uuid4(),
            "tenant_id": None,
            "name": "Aprobador",
            "code": "aprobador",
            "description": "Revisa y aprueba campañas",
            "is_system": True,
        },
        {
            "id": uuid.uuid4(),
            "tenant_id": None,
            "name": "Visualizador",
            "code": "visualizador",
            "description": "Solo ve dashboard y reportes",
            "is_system": True,
        },
    ]
    op.bulk_insert(roles_table, roles_seed)

    role_id_by_code = {r["code"]: r["id"] for r in roles_seed}

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
        {"id": uuid.uuid4(), "code": "dashboard", "name": "Dashboard", "group_name": "Portal", "route": "/", "icon": "LayoutDashboard", "order_index": 1, "is_portal": False, "status": "active"},
        {"id": uuid.uuid4(), "code": "campaigns", "name": "Campañas", "group_name": "Portal", "route": "/campanas", "icon": "Megaphone", "order_index": 2, "is_portal": False, "status": "active"},
        {"id": uuid.uuid4(), "code": "scheduled_messages", "name": "Mensajes programados", "group_name": "Portal", "route": "/mensajes-programados", "icon": "CalendarClock", "order_index": 3, "is_portal": False, "status": "active"},
        {"id": uuid.uuid4(), "code": "contacts", "name": "Contactos", "group_name": "Portal", "route": "/contactos", "icon": "Users", "order_index": 4, "is_portal": False, "status": "active"},
        {"id": uuid.uuid4(), "code": "segments", "name": "Segmentos", "group_name": "Portal", "route": "/segmentos", "icon": "Layers", "order_index": 5, "is_portal": False, "status": "active"},
        {"id": uuid.uuid4(), "code": "templates", "name": "Plantillas", "group_name": "Portal", "route": "/plantillas", "icon": "MessageSquare", "order_index": 6, "is_portal": False, "status": "active"},
        {"id": uuid.uuid4(), "code": "surveys", "name": "Encuestas", "group_name": "Portal", "route": "/encuestas", "icon": "ClipboardList", "order_index": 7, "is_portal": False, "status": "active"},
        {"id": uuid.uuid4(), "code": "reports", "name": "Reportes", "group_name": "Portal", "route": "/reportes", "icon": "BarChart3", "order_index": 8, "is_portal": False, "status": "active"},
        {"id": uuid.uuid4(), "code": "users", "name": "Usuarios", "group_name": "Administración", "route": "/usuarios", "icon": "UserCog", "order_index": 9, "is_portal": False, "status": "active"},
        {"id": uuid.uuid4(), "code": "settings", "name": "Configuración", "group_name": "Administración", "route": "/configuracion", "icon": "Settings", "order_index": 10, "is_portal": False, "status": "active"},
    ]
    op.bulk_insert(components_table, components_seed)
    component_id_by_code = {c["code"]: c["id"] for c in components_seed}

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

    comunicador_full = ["dashboard", "campaigns", "scheduled_messages", "contacts", "segments", "templates", "surveys", "reports"]
    for code in comunicador_full:
        rc_rows.append(_row("comunicador", code, view=True, create=True, edit=True, delete=False, export=True))

    aprobador_view_edit = ["dashboard", "campaigns", "scheduled_messages", "reports"]
    for code in aprobador_view_edit:
        rc_rows.append(_row("aprobador", code, view=True, create=False, edit=True, delete=False, export=True))

    for code in ("dashboard", "reports"):
        rc_rows.append(_row("visualizador", code, view=True, create=False, edit=False, delete=False, export=True))

    op.bulk_insert(role_components_table, rc_rows)


def downgrade() -> None:
    op.drop_table("workspace_settings")
    op.drop_table("surveys")
    op.drop_table("campaigns")
    op.drop_table("message_templates")
    op.drop_table("segments")
    op.drop_table("contacts")
    op.drop_table("user_roles")
    op.drop_table("users")
    op.drop_table("role_components")
    op.drop_table("ui_components")
    op.drop_table("roles")
    op.drop_table("tenants")
