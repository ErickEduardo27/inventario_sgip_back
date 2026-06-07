"""Catálogo sedes/áreas/cargos y FK en contactos; criterios de segmentos por ID.

Revision ID: 004_contact_catalog
Revises: 003_add_omnichannel_component
Create Date: 2026-05-03
"""

from __future__ import annotations

import json
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "004_contact_catalog"
down_revision = "003_add_omnichannel_component"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "catalog_sites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_catalog_sites_tenant_name"),
    )
    op.create_index(op.f("ix_catalog_sites_tenant_id"), "catalog_sites", ["tenant_id"])

    op.create_table(
        "catalog_areas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_catalog_areas_tenant_name"),
    )
    op.create_index(op.f("ix_catalog_areas_tenant_id"), "catalog_areas", ["tenant_id"])

    op.create_table(
        "catalog_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_catalog_positions_tenant_name"),
    )
    op.create_index(op.f("ix_catalog_positions_tenant_id"), "catalog_positions", ["tenant_id"])

    op.add_column("contacts", sa.Column("site_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("contacts", sa.Column("area_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("contacts", sa.Column("position_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_contacts_catalog_site_id",
        "contacts",
        "catalog_sites",
        ["site_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_contacts_catalog_area_id",
        "contacts",
        "catalog_areas",
        ["area_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_contacts_catalog_position_id",
        "contacts",
        "catalog_positions",
        ["position_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_contacts_site_id"), "contacts", ["site_id"])
    op.create_index(op.f("ix_contacts_area_id"), "contacts", ["area_id"])
    op.create_index(op.f("ix_contacts_position_id"), "contacts", ["position_id"])

    bind = op.get_bind()

    col_sql = {"site": "site", "area": "area", "position": '"position"'}

    def migrate_catalog_column(tenant_id: uuid.UUID, col: str, catalog_table: str) -> None:
        csql = col_sql[col]
        rows = bind.execute(
            text(
                f"""
                SELECT DISTINCT trim({csql}) AS v FROM contacts
                WHERE tenant_id = :tid AND {csql} IS NOT NULL AND trim({csql}) <> ''
                  AND is_deleted = false
                """
            ),
            {"tid": tenant_id},
        ).fetchall()
        for (val,) in rows:
            rid = bind.execute(
                text(f"SELECT id FROM {catalog_table} WHERE tenant_id = :tid AND name = :n AND is_deleted = false"),
                {"tid": tenant_id, "n": val},
            ).scalar()
            if rid is None:
                rid = uuid.uuid4()
                bind.execute(
                    text(
                        f"""
                        INSERT INTO {catalog_table}
                            (id, created_at, updated_at, is_deleted, tenant_id, name)
                        VALUES (:id, now(), now(), false, :tid, :name)
                        """
                    ),
                    {"id": rid, "tid": tenant_id, "name": val},
                )
            fk_col = {"site": "site_id", "area": "area_id", "position": "position_id"}[col]
            bind.execute(
                text(
                    f"""
                    UPDATE contacts SET {fk_col} = :rid
                    WHERE tenant_id = :tid AND trim({csql}) = :val AND is_deleted = false
                    """
                ),
                {"rid": rid, "tid": tenant_id, "val": val},
            )

    tenants = bind.execute(text("SELECT id FROM tenants")).fetchall()
    for (tid,) in tenants:
        migrate_catalog_column(tid, "site", "catalog_sites")
        migrate_catalog_column(tid, "area", "catalog_areas")
        migrate_catalog_column(tid, "position", "catalog_positions")

    # Segment criteria: legacy string lists -> UUID lists
    segs = bind.execute(text("SELECT id, tenant_id, criteria FROM segments WHERE is_deleted = false")).fetchall()
    for seg_id, tenant_id, criteria in segs:
        criteria = dict(criteria or {})

        def names_to_ids(catalog_table: str, names: list) -> list[str]:
            out: list[str] = []
            for raw in names:
                if raw is None or not str(raw).strip():
                    continue
                row = bind.execute(
                    text(
                        f"SELECT id FROM {catalog_table} WHERE tenant_id = :t AND name = :n AND is_deleted = false"
                    ),
                    {"t": tenant_id, "n": str(raw).strip()},
                ).scalar()
                if row:
                    out.append(str(row))
            return out

        if "sites" in criteria:
            legacy = criteria.pop("sites") or []
            merged = list(dict.fromkeys([*(criteria.get("site_ids") or []), *names_to_ids("catalog_sites", legacy)]))
            if merged:
                criteria["site_ids"] = merged
        if "areas" in criteria:
            legacy = criteria.pop("areas") or []
            merged = list(dict.fromkeys([*(criteria.get("area_ids") or []), *names_to_ids("catalog_areas", legacy)]))
            if merged:
                criteria["area_ids"] = merged
        if "positions" in criteria:
            legacy = criteria.pop("positions") or []
            merged = list(
                dict.fromkeys([*(criteria.get("position_ids") or []), *names_to_ids("catalog_positions", legacy)])
            )
            if merged:
                criteria["position_ids"] = merged

        bind.execute(
            text("UPDATE segments SET criteria = CAST(:js AS jsonb) WHERE id = :id"),
            {"js": json.dumps(criteria), "id": seg_id},
        )

    op.drop_index(op.f("ix_contacts_site"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_area"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_position"), table_name="contacts")
    op.drop_column("contacts", "site")
    op.drop_column("contacts", "area")
    op.drop_column("contacts", "position")

    exists = bind.execute(text("SELECT 1 FROM ui_components WHERE code = 'contact_catalog' LIMIT 1")).scalar()
    if not exists:
        comp_id = uuid.uuid4()
        bind.execute(
            text(
                """
                INSERT INTO ui_components (
                    id, created_at, updated_at, code, name, group_name, route, icon, order_index, is_portal, status
                )
                VALUES (
                    :id, now(), now(), 'contact_catalog', 'Catálogo contactos', 'Administración',
                    '/catalogo-contactos', 'Tags', 12, false, 'active'
                )
                """
            ),
            {"id": comp_id},
        )
        res = bind.execute(text("SELECT id, code FROM roles WHERE tenant_id IS NULL AND is_deleted = false"))
        role_id_by_code = {str(row[1]): row[0] for row in res}
        perms = [
            ("administrador", True, True, True, True, True),
            ("comunicador", True, True, True, False, True),
            ("aprobador", True, False, False, False, False),
            ("visualizador", True, False, False, False, False),
        ]
        for role_code, v, c, e, d, x in perms:
            rid = role_id_by_code.get(role_code)
            if rid is None:
                continue
            bind.execute(
                text(
                    """
                    INSERT INTO role_components (
                        role_id, component_id, can_view, can_create, can_edit, can_delete, can_export, scope
                    )
                    VALUES (:rid, :cid, :v, :c, :e, :d, :x, 'tenant')
                    """
                ),
                {"rid": rid, "cid": comp_id, "v": v, "c": c, "e": e, "d": d, "x": x},
            )


def downgrade() -> None:
    pass
