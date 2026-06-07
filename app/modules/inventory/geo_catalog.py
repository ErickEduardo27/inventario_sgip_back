"""Consultas de catálogos geográficos (scope activo, orden por descripción)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.inventory.geo_models import InvCountry, InvDepartment, InvDistrict, InvProvince


def _catalog_row(id_val: str, description: str) -> dict[str, str | bool]:
    return {"id": id_val, "description": description, "active": True}


def list_countries(db: Session, *, active_only: bool = True) -> list[dict]:
    stmt = select(InvCountry)
    if active_only:
        stmt = stmt.where(InvCountry.active.is_(True))
    stmt = stmt.order_by(InvCountry.description.asc())
    rows = db.scalars(stmt).all()
    return [_catalog_row(r.id, r.description) for r in rows]


def list_departments(db: Session, *, active_only: bool = True) -> list[dict]:
    stmt = select(InvDepartment)
    if active_only:
        stmt = stmt.where(InvDepartment.active.is_(True))
    stmt = stmt.order_by(InvDepartment.description.asc())
    rows = db.scalars(stmt).all()
    return [_catalog_row(r.id, r.description) for r in rows]


def list_provinces(
    db: Session,
    department_id: str | None = None,
    *,
    active_only: bool = True,
) -> list[dict]:
    stmt = select(InvProvince)
    if department_id:
        stmt = stmt.where(InvProvince.department_id == department_id)
    if active_only:
        stmt = stmt.where(InvProvince.active.is_(True))
    stmt = stmt.order_by(InvProvince.description.asc())
    rows = db.scalars(stmt).all()
    return [_catalog_row(r.id, r.description) for r in rows]


def list_districts(
    db: Session,
    province_id: str | None = None,
    *,
    active_only: bool = True,
) -> list[dict]:
    stmt = select(InvDistrict)
    if province_id:
        stmt = stmt.where(InvDistrict.province_id == province_id)
    if active_only:
        stmt = stmt.where(InvDistrict.active.is_(True))
    stmt = stmt.order_by(InvDistrict.description.asc())
    rows = db.scalars(stmt).all()
    return [_catalog_row(r.id, r.description) for r in rows]


def validate_establishment_geo_ids(
    db: Session,
    country_id: str | None,
    department_id: str | None,
    province_id: str | None,
    district_id: str | None,
) -> None:
    if country_id and not db.get(InvCountry, country_id):
        raise ValueError(f"País no válido: {country_id}")
    if department_id and not db.get(InvDepartment, department_id):
        raise ValueError(f"Departamento no válido: {department_id}")
    if province_id:
        prov = db.get(InvProvince, province_id)
        if not prov:
            raise ValueError(f"Provincia no válida: {province_id}")
        if department_id and prov.department_id != department_id:
            raise ValueError("La provincia no pertenece al departamento indicado")
    if district_id:
        dist = db.get(InvDistrict, district_id)
        if not dist:
            raise ValueError(f"Distrito no válido: {district_id}")
        if province_id and dist.province_id != province_id:
            raise ValueError("El distrito no pertenece a la provincia indicada")
