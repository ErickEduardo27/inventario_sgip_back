"""Catálogos geográficos (countries, departments, provinces, districts) y FK en establishments.

Revision ID: 021_geo_catalog_fk
Revises: 020_user_inventory_counters
Create Date: 2026-06-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "021_geo_catalog_fk"
down_revision = "020_user_inventory_counters"
branch_labels = None
depends_on = None

# Catálogo inicial Perú (alineado con front/src/data/peru-geo.ts)
_PERU_SEED = {
    "country": ("PE", "PERU"),
    "departments": [
        ("14", "Lima", [("1401", "Lima", [("140101", "Lima"), ("140116", "San Isidro"), ("140122", "Miraflores"), ("140124", "Surco")]), ("1405", "Huaura", [("140501", "Huacho"), ("140502", "Hualmay")])]),
        ("04", "Arequipa", [("0401", "Arequipa", [("040101", "Arequipa"), ("040102", "Cayma"), ("040103", "Cerro Colorado")])]),
        ("16", "Loreto", [("1601", "Maynas", [("160101", "Iquitos"), ("160102", "Punchana")])]),
    ],
}


def _seed_geo(bind) -> None:
    countries = sa.table(
        "countries",
        sa.column("id", sa.String(2)),
        sa.column("description", sa.String(200)),
        sa.column("active", sa.Boolean),
    )
    departments = sa.table(
        "departments",
        sa.column("id", sa.String(2)),
        sa.column("description", sa.String(200)),
        sa.column("active", sa.Boolean),
    )
    provinces = sa.table(
        "provinces",
        sa.column("id", sa.String(4)),
        sa.column("department_id", sa.String(2)),
        sa.column("description", sa.String(200)),
        sa.column("active", sa.Boolean),
    )
    districts = sa.table(
        "districts",
        sa.column("id", sa.String(6)),
        sa.column("province_id", sa.String(4)),
        sa.column("description", sa.String(200)),
        sa.column("active", sa.Boolean),
    )

    cid, cdesc = _PERU_SEED["country"]
    op.bulk_insert(countries, [{"id": cid, "description": cdesc, "active": True}])

    dept_rows: list[dict] = []
    prov_rows: list[dict] = []
    dist_rows: list[dict] = []
    for dept_id, dept_name, provs in _PERU_SEED["departments"]:
        dept_rows.append({"id": dept_id, "description": dept_name, "active": True})
        for prov_id, prov_name, dists in provs:
            prov_rows.append(
                {"id": prov_id, "department_id": dept_id, "description": prov_name, "active": True}
            )
            for dist_id, dist_name in dists:
                dist_rows.append(
                    {"id": dist_id, "province_id": prov_id, "description": dist_name, "active": True}
                )

    if dept_rows:
        op.bulk_insert(departments, dept_rows)
    if prov_rows:
        op.bulk_insert(provinces, prov_rows)
    if dist_rows:
        op.bulk_insert(districts, dist_rows)


def upgrade() -> None:
    op.create_table(
        "countries",
        sa.Column("id", sa.String(length=2), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "departments",
        sa.Column("id", sa.String(length=2), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "provinces",
        sa.Column("id", sa.String(length=4), nullable=False),
        sa.Column("department_id", sa.String(length=2), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["department_id"], ["departments.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_provinces_department_id"), "provinces", ["department_id"], unique=False)

    op.create_table(
        "districts",
        sa.Column("id", sa.String(length=6), nullable=False),
        sa.Column("province_id", sa.String(length=4), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.ForeignKeyConstraint(["province_id"], ["provinces.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_districts_province_id"), "districts", ["province_id"], unique=False)

    _seed_geo(None)

    # Limpiar referencias huérfanas antes de crear FK
    op.execute(
        """
        UPDATE establishments SET country_id = NULL
        WHERE country_id IS NOT NULL
          AND country_id NOT IN (SELECT id FROM countries)
        """
    )
    op.execute(
        """
        UPDATE establishments SET department_id = NULL
        WHERE department_id IS NOT NULL
          AND department_id NOT IN (SELECT id FROM departments)
        """
    )
    op.execute(
        """
        UPDATE establishments SET province_id = NULL
        WHERE province_id IS NOT NULL
          AND province_id NOT IN (SELECT id FROM provinces)
        """
    )
    op.execute(
        """
        UPDATE establishments SET district_id = NULL
        WHERE district_id IS NOT NULL
          AND district_id NOT IN (SELECT id FROM districts)
        """
    )

    # Normalizar IDs existentes en establishments antes de acortar columnas
    op.execute(
        """
        UPDATE establishments SET country_id = LEFT(TRIM(country_id), 2)
        WHERE country_id IS NOT NULL AND LENGTH(TRIM(country_id)) > 0
        """
    )
    op.execute(
        """
        UPDATE establishments SET department_id = LEFT(TRIM(department_id), 2)
        WHERE department_id IS NOT NULL AND LENGTH(TRIM(department_id)) > 0
        """
    )
    op.execute(
        """
        UPDATE establishments SET province_id = LEFT(TRIM(province_id), 4)
        WHERE province_id IS NOT NULL AND LENGTH(TRIM(province_id)) > 0
        """
    )
    op.execute(
        """
        UPDATE establishments SET district_id = LEFT(TRIM(district_id), 6)
        WHERE district_id IS NOT NULL AND LENGTH(TRIM(district_id)) > 0
        """
    )

    op.alter_column(
        "establishments",
        "country_id",
        existing_type=sa.String(length=50),
        type_=sa.String(length=2),
        existing_nullable=True,
    )
    op.alter_column(
        "establishments",
        "department_id",
        existing_type=sa.String(length=50),
        type_=sa.String(length=2),
        existing_nullable=True,
    )
    op.alter_column(
        "establishments",
        "province_id",
        existing_type=sa.String(length=50),
        type_=sa.String(length=4),
        existing_nullable=True,
    )
    op.alter_column(
        "establishments",
        "district_id",
        existing_type=sa.String(length=50),
        type_=sa.String(length=6),
        existing_nullable=True,
    )

    op.create_foreign_key(
        "fk_establishments_country_id",
        "establishments",
        "countries",
        ["country_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_establishments_department_id",
        "establishments",
        "departments",
        ["department_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_establishments_province_id",
        "establishments",
        "provinces",
        ["province_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_establishments_district_id",
        "establishments",
        "districts",
        ["district_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_establishments_district_id", "establishments", type_="foreignkey")
    op.drop_constraint("fk_establishments_province_id", "establishments", type_="foreignkey")
    op.drop_constraint("fk_establishments_department_id", "establishments", type_="foreignkey")
    op.drop_constraint("fk_establishments_country_id", "establishments", type_="foreignkey")

    op.alter_column(
        "establishments",
        "district_id",
        existing_type=sa.String(length=6),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
    op.alter_column(
        "establishments",
        "province_id",
        existing_type=sa.String(length=4),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
    op.alter_column(
        "establishments",
        "department_id",
        existing_type=sa.String(length=2),
        type_=sa.String(length=50),
        existing_nullable=True,
    )
    op.alter_column(
        "establishments",
        "country_id",
        existing_type=sa.String(length=2),
        type_=sa.String(length=50),
        existing_nullable=True,
    )

    op.drop_index(op.f("ix_districts_province_id"), table_name="districts")
    op.drop_table("districts")
    op.drop_index(op.f("ix_provinces_department_id"), table_name="provinces")
    op.drop_table("provinces")
    op.drop_table("departments")
    op.drop_table("countries")
