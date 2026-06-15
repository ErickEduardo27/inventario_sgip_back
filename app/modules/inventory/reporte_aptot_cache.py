"""Reconstrucción y encolado del cache ``reporte_aptot_cache``."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from app.modules.inventory import models as m
from app.modules.inventory.reporte_aptot_sql import REPORTE_APTOT_INSERT_SQL
from app.modules.tenants import models as _tenant_models  # noqa: F401 — FK tenants en metadata

logger = logging.getLogger(__name__)

APTOT_IMPORT_MODULES = frozenset(
    {
        "margesi",
        "margesi_moment",
        "hoja_captura",
        "cards",
    }
)


def rebuild_reporte_aptot_cache(db: Session, tenant_id: UUID) -> dict[str, int | str]:
    """Borra y repuebla el cache del tenant (equivalente al SP de descarga total)."""
    refreshed_at = datetime.now(timezone.utc)
    db.execute(
        delete(m.InvReporteAptotCache).where(m.InvReporteAptotCache.tenant_id == tenant_id),
    )
    db.execute(
        text(REPORTE_APTOT_INSERT_SQL),
        {"tenant_id": str(tenant_id), "refreshed_at": refreshed_at},
    )
    row_count = db.scalar(
        select(func.count())
        .select_from(m.InvReporteAptotCache)
        .where(m.InvReporteAptotCache.tenant_id == tenant_id),
    )
    meta = db.get(m.InvReporteAptotCacheMeta, tenant_id)
    if meta is None:
        meta = m.InvReporteAptotCacheMeta(tenant_id=tenant_id)
    meta.refreshed_at = refreshed_at
    meta.row_count = int(row_count or 0)
    meta.status = "ready"
    meta.message = ""
    db.add(meta)
    db.commit()
    return {
        "tenant_id": str(tenant_id),
        "row_count": int(row_count or 0),
        "refreshed_at": refreshed_at.isoformat(),
    }


def mark_reporte_aptot_cache_refreshing(db: Session, tenant_id: UUID) -> None:
    meta = db.get(m.InvReporteAptotCacheMeta, tenant_id)
    if meta is None:
        meta = m.InvReporteAptotCacheMeta(tenant_id=tenant_id)
    meta.status = "refreshing"
    meta.message = "Actualizando reporte APTOT…"
    db.add(meta)
    db.commit()


def schedule_reporte_aptot_cache_refresh(tenant_id: UUID, *, countdown: int = 2) -> None:
    """Encola reconstrucción asíncrona vía Celery (respuesta inmediata al usuario)."""
    try:
        from app.tasks.reporte_aptot import refresh_reporte_aptot_cache_task

        refresh_reporte_aptot_cache_task.apply_async(
            args=[str(tenant_id)],
            countdown=countdown,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo encolar refresh reporte APTOT: %s", exc)


def maybe_schedule_after_import(module: str, tenant_id: UUID) -> None:
    if module in APTOT_IMPORT_MODULES:
        schedule_reporte_aptot_cache_refresh(tenant_id)
