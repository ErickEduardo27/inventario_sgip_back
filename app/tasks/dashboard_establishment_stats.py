"""Tareas Celery: actualizar cache del resumen por local del dashboard."""

from __future__ import annotations

from uuid import UUID

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.modules.inventory.dashboard_establishment_stats_cache import (
    rebuild_dashboard_establishment_stats_for_establishment,
    rebuild_dashboard_establishment_stats_tenant,
)


@celery_app.task(bind=True, name="dashboard.refresh_establishment_stats")
def refresh_dashboard_establishment_stats_task(
    self,
    tenant_id: str,
    establishment_id: int,
) -> dict:
    tenant_uuid = UUID(tenant_id)
    with SessionLocal() as db:
        try:
            result = rebuild_dashboard_establishment_stats_for_establishment(
                db,
                tenant_uuid,
                establishment_id,
            )
            return {"success": True, **result}
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            return {
                "success": False,
                "tenant_id": tenant_id,
                "establishment_id": establishment_id,
                "message": str(exc),
            }


@celery_app.task(bind=True, name="dashboard.refresh_establishment_stats_bulk")
def refresh_dashboard_establishment_stats_bulk_task(
    self,
    tenant_id: str,
    establishment_ids: list[int],
) -> dict:
    tenant_uuid = UUID(tenant_id)
    updated = 0
    errors: list[str] = []
    with SessionLocal() as db:
        for eid in establishment_ids:
            try:
                rebuild_dashboard_establishment_stats_for_establishment(db, tenant_uuid, int(eid))
                updated += 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                errors.append(f"{eid}: {exc}")
    return {
        "success": not errors,
        "tenant_id": tenant_id,
        "updated": updated,
        "errors": errors,
    }


@celery_app.task(bind=True, name="dashboard.refresh_establishment_stats_tenant")
def refresh_dashboard_establishment_stats_tenant_task(self, tenant_id: str) -> dict:
    tenant_uuid = UUID(tenant_id)
    with SessionLocal() as db:
        try:
            result = rebuild_dashboard_establishment_stats_tenant(db, tenant_uuid)
            return {"success": True, **result}
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            return {"success": False, "tenant_id": tenant_id, "message": str(exc)}
