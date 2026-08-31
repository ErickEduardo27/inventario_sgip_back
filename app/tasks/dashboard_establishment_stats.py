"""Tareas Celery: actualizar cache del resumen por local del dashboard."""

from __future__ import annotations

from uuid import UUID

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.modules.inventory.dashboard_establishment_stats_cache import (
    end_dashboard_stats_run,
    rebuild_dashboard_establishment_stats_for_establishment,
    rebuild_dashboard_establishment_stats_tenant,
    try_begin_dashboard_stats_run,
)


@celery_app.task(bind=True, name="dashboard.apply_establishment_stats_delta", ignore_result=True)
def apply_dashboard_establishment_stats_delta_task(
    self,
    tenant_id: str,
    changes_payload: list[dict] | None = None,
    *,
    deltas_payload: dict[str, dict[str, int]] | None = None,
) -> dict:
    from app.modules.inventory.dashboard_establishment_stats_incremental import (
        EstablishmentStatsChange,
        apply_establishment_deltas,
        apply_establishment_stats_changes,
    )

    tenant_uuid = UUID(tenant_id)
    with SessionLocal() as db:
        try:
            if deltas_payload:
                normalized = {
                    int(est_id): {k: int(v) for k, v in deltas.items()}
                    for est_id, deltas in deltas_payload.items()
                }
                updated = apply_establishment_deltas(db, tenant_uuid, normalized)
            elif changes_payload:
                changes = [EstablishmentStatsChange.from_dict(raw) for raw in changes_payload]
                updated = apply_establishment_stats_changes(db, tenant_uuid, changes)
            else:
                return {"success": False, "tenant_id": tenant_id, "message": "Sin payload"}
            return {"success": True, "tenant_id": tenant_id, "updated": updated}
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            return {"success": False, "tenant_id": tenant_id, "message": str(exc)}


@celery_app.task(bind=True, name="dashboard.refresh_establishment_stats", ignore_result=True)
def refresh_dashboard_establishment_stats_task(
    self,
    tenant_id: str,
    establishment_id: int,
) -> dict:
    tenant_uuid = UUID(tenant_id)
    if not try_begin_dashboard_stats_run(tenant_uuid, establishment_id):
        return {
            "success": True,
            "skipped": True,
            "tenant_id": tenant_id,
            "establishment_id": establishment_id,
            "message": "Recálculo ya en curso",
        }
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
        finally:
            end_dashboard_stats_run(tenant_uuid, establishment_id)


@celery_app.task(bind=True, name="dashboard.refresh_establishment_stats_bulk", ignore_result=True)
def refresh_dashboard_establishment_stats_bulk_task(
    self,
    tenant_id: str,
    establishment_ids: list[int],
) -> dict:
    tenant_uuid = UUID(tenant_id)
    updated = 0
    skipped = 0
    errors: list[str] = []
    with SessionLocal() as db:
        for eid in establishment_ids:
            est_id = int(eid)
            if not try_begin_dashboard_stats_run(tenant_uuid, est_id):
                skipped += 1
                continue
            try:
                rebuild_dashboard_establishment_stats_for_establishment(db, tenant_uuid, est_id)
                updated += 1
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                errors.append(f"{eid}: {exc}")
            finally:
                end_dashboard_stats_run(tenant_uuid, est_id)
    return {
        "success": not errors,
        "tenant_id": tenant_id,
        "updated": updated,
        "skipped": skipped,
        "errors": errors,
    }


@celery_app.task(bind=True, name="dashboard.refresh_establishment_stats_tenant", ignore_result=True)
def refresh_dashboard_establishment_stats_tenant_task(self, tenant_id: str) -> dict:
    tenant_uuid = UUID(tenant_id)
    if not try_begin_dashboard_stats_run(tenant_uuid):
        return {
            "success": True,
            "skipped": True,
            "tenant_id": tenant_id,
            "message": "Recálculo tenant ya en curso",
        }
    with SessionLocal() as db:
        try:
            result = rebuild_dashboard_establishment_stats_tenant(db, tenant_uuid)
            return {"success": True, **result}
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            return {"success": False, "tenant_id": tenant_id, "message": str(exc)}
        finally:
            end_dashboard_stats_run(tenant_uuid)
