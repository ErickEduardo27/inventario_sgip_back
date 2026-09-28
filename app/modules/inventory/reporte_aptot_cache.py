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


def _lock_tenant_rebuild(db: Session, tenant_id: UUID) -> None:
    """Serializa reconstrucciones del mismo tenant (se libera al commit/rollback).

    Sin esto, dos tareas simultáneas hacen DELETE + INSERT cruzados y la segunda choca con
    ``uq_reporte_aptot_cache_source`` al insertar filas que la primera ya confirmó.
    """
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"reporte_aptot_cache:{tenant_id}"},
    )


def rebuild_reporte_aptot_cache(
    db: Session,
    tenant_id: UUID,
    *,
    requested_at: datetime | None = None,
) -> dict[str, int | str]:
    """Borra y repuebla el cache del tenant (equivalente al SP de descarga total).

    Si ``requested_at`` es anterior a la última reconstrucción terminada, esa reconstrucción ya
    incluye los cambios que motivaron la solicitud y no se repite.
    """
    _lock_tenant_rebuild(db, tenant_id)
    meta = db.execute(
        select(m.InvReporteAptotCacheMeta)
        .where(m.InvReporteAptotCacheMeta.tenant_id == tenant_id)
        .execution_options(populate_existing=True),
    ).scalar_one_or_none()
    if (
        requested_at is not None
        and meta is not None
        and meta.refreshed_at is not None
        and meta.refreshed_at >= requested_at
    ):
        result: dict[str, int | str] = {
            "tenant_id": str(tenant_id),
            "row_count": int(meta.row_count or 0),
            "refreshed_at": meta.refreshed_at.isoformat(),
            "skipped": "already_fresh",
        }
        meta.status = "ready"
        meta.message = ""
        db.add(meta)
        db.commit()
        return result

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
            kwargs={"requested_at": datetime.now(timezone.utc).isoformat()},
            countdown=countdown,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("No se pudo encolar refresh reporte APTOT: %s", exc)


def maybe_schedule_after_import(module: str, tenant_id: UUID) -> None:
    if module in APTOT_IMPORT_MODULES:
        schedule_reporte_aptot_cache_refresh(tenant_id)
