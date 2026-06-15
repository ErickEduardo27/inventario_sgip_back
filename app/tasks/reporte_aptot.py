"""Tarea Celery: reconstruir ``reporte_aptot_cache`` por tenant."""

from __future__ import annotations

from uuid import UUID

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.modules.inventory import models as m
from app.modules.inventory.reporte_aptot_cache import (
    mark_reporte_aptot_cache_refreshing,
    rebuild_reporte_aptot_cache,
)


@celery_app.task(bind=True, name="reporte.refresh_aptot_cache")
def refresh_reporte_aptot_cache_task(self, tenant_id: str) -> dict:
    tenant_uuid = UUID(tenant_id)
    with SessionLocal() as db:
        try:
            mark_reporte_aptot_cache_refreshing(db, tenant_uuid)
            result = rebuild_reporte_aptot_cache(db, tenant_uuid)
            return {"success": True, **result}
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            row = db.get(m.InvReporteAptotCacheMeta, tenant_uuid)
            if row is not None:
                row.status = "error"
                row.message = str(exc)[:500]
                db.add(row)
                db.commit()
            return {"success": False, "tenant_id": tenant_id, "message": str(exc)}
