"""Reporte APTOT por departamento: departamentos con locales del tenant y sus conteos."""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.inventory import models as m
from app.modules.inventory.geo_models import InvDepartment


def slug(value: str) -> str:
    """Texto seguro para nombres de archivo (sin tildes ni espacios)."""
    plain = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^A-Za-z0-9]+", "_", plain).strip("_").lower() or "departamento"


def list_departments(db: Session, tenant_id: UUID) -> list[dict[str, Any]]:
    """Departamentos que tienen al menos un local del tenant, con cuántos locales tiene cada uno."""
    rows = db.execute(
        select(InvDepartment.id, InvDepartment.description, func.count(m.InvEstablishment.id))
        .join(m.InvEstablishment, m.InvEstablishment.department_id == InvDepartment.id)
        .where(m.InvEstablishment.tenant_id == tenant_id)
        .group_by(InvDepartment.id, InvDepartment.description)
        .order_by(InvDepartment.description)
    ).all()
    return [{"id": str(i), "description": str(d or i), "locales": int(n)} for i, d, n in rows]


def department_summary(db: Session, tenant_id: UUID, department_id: str) -> dict[str, Any] | None:
    """Datos del departamento si tiene locales del tenant; ``None`` si no existe o no tiene locales."""
    for row in list_departments(db, tenant_id):
        if row["id"] == str(department_id):
            return row
    return None
