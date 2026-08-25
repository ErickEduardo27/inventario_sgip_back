"""Feature flags: módulos habilitados por tenant (empaquetado de producto).

Independiente del RBAC: un módulo apagado no aparece aunque el usuario tenga permiso.
`settings` no se puede desactivar para no dejar el tenant sin consola de marca.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.constants import INVENTORY_UI_COMPONENT_CODES

LOCKED_FEATURES: frozenset[str] = frozenset({"settings"})

FEATURE_CATALOG: tuple[dict[str, str], ...] = (
    {"code": "dashboard", "name": "Dashboard", "group": "Tablas"},
    {"code": "locales", "name": "Locales", "group": "Tablas"},
    {"code": "locales_mapa", "name": "Mapa de locales", "group": "Tablas"},
    {"code": "ambientes", "name": "Ambientes", "group": "Tablas"},
    {"code": "centro_costo", "name": "Centro de costo", "group": "Tablas"},
    {"code": "personas", "name": "Personas", "group": "Tablas"},
    {"code": "list_sbn", "name": "Catálogo SBN", "group": "Tablas"},
    {"code": "margesi", "name": "Patrimonio (Margesi)", "group": "Tablas"},
    {"code": "hoja_captura", "name": "Hojas de captura", "group": "Inventario físico"},
    {"code": "bienes", "name": "Bienes inventariados", "group": "Inventario físico"},
    {"code": "imagenes", "name": "Imágenes", "group": "Inventario físico"},
    {"code": "asistencia", "name": "Asistencia", "group": "Operación"},
    {"code": "panel_asistencia", "name": "Panel de asistencia", "group": "Operación"},
    {"code": "reporte_aptot", "name": "Reporte APTOT", "group": "Reportes"},
    {"code": "reporte_aptot_locales", "name": "APTOT por locales", "group": "Reportes"},
    {"code": "reporte_locales", "name": "Reporte Locales", "group": "Reportes"},
    {"code": "conciliacion", "name": "Conciliación", "group": "Conciliación"},
    {"code": "conciliacion_sbn", "name": "Conciliación SBN", "group": "Conciliación"},
    {"code": "desconciliacion", "name": "Desconciliación", "group": "Conciliación"},
    {"code": "desconciliacion_sbn", "name": "Desconciliación SBN", "group": "Conciliación"},
    {"code": "no_conciliables", "name": "No conciliables", "group": "Conciliación"},
    {"code": "usuarios", "name": "Usuarios", "group": "Administración"},
    {"code": "perfiles", "name": "Perfiles", "group": "Administración"},
    {"code": "settings", "name": "Entorno y tenant", "group": "Administración"},
    {"code": "auditoria", "name": "Auditoría", "group": "Administración"},
)

_CATALOG_CODES = frozenset(item["code"] for item in FEATURE_CATALOG)
if _CATALOG_CODES != INVENTORY_UI_COMPONENT_CODES:
    missing = INVENTORY_UI_COMPONENT_CODES - _CATALOG_CODES
    extra = _CATALOG_CODES - INVENTORY_UI_COMPONENT_CODES
    raise RuntimeError(f"FEATURE_CATALOG desalineado: missing={missing} extra={extra}")


def default_features() -> dict[str, bool]:
    return {code: True for code in INVENTORY_UI_COMPONENT_CODES}


def merge_features(stored: dict[str, Any] | None) -> dict[str, bool]:
    out = default_features()
    if stored:
        for key, value in stored.items():
            if key in out and key not in LOCKED_FEATURES:
                out[key] = bool(value)
    for locked in LOCKED_FEATURES:
        if locked in out:
            out[locked] = True
    return out


def is_feature_enabled(db: Session, tenant_id: UUID, code: str) -> bool:
    """True si el módulo no está catalogado o está activo para el tenant."""
    if code not in INVENTORY_UI_COMPONENT_CODES:
        return True
    if code in LOCKED_FEATURES:
        return True
    from app.modules.settings.models import WorkspaceSettings

    row = db.scalar(select(WorkspaceSettings).where(WorkspaceSettings.tenant_id == tenant_id))
    flags = merge_features(row.feature_flags if row else None)
    return bool(flags.get(code, True))
