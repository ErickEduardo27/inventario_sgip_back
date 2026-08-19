"""Tareas Celery: exportación CSV → GCS → descarga_archivos."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from app.celery_app import celery_app
from app.core.export_storage import resolve_download_url, upload_export_file
from app.db.session import SessionLocal
from app.modules.inventory import descarga_archivos_service as dl_svc
from app.modules.inventory.csv_export import copy_query_to_csv_bytes, csv_bytes_to_xlsx_bytes
from app.modules.inventory.export_queries import build_item_cards_export_query, get_export_query
from app.modules.inventory.schemas import RecordQuery


def _progress_meta(progress: int, message: str) -> dict:
    return {"progress": progress, "message": message}


@celery_app.task(bind=True, name="export.reporte_aptot_csv")
def export_reporte_aptot_csv_task(self, job_id: str, tenant_id: str) -> dict:
    job_uuid = UUID(job_id)
    tenant_uuid = UUID(tenant_id)

    try:
        with SessionLocal() as db:
            row = dl_svc.get_descarga_archivo(db, job_uuid, tenant_uuid)
            if row is None:
                return {"success": False, "message": "Trabajo de descarga no encontrado"}
            dl_svc.mark_processing(db, row)
            db.commit()

        self.update_state(state="PROGRESS", meta=_progress_meta(10, "Generando CSV…"))

        inner_sql, filename_base = get_export_query("reporte_aptot")
        stamp = date.today().isoformat()
        filename = f"{filename_base}_{stamp}.csv"
        payload = copy_query_to_csv_bytes(inner_sql, (str(tenant_uuid),))
        content = b"\xef\xbb\xbf" + payload

        self.update_state(
            state="PROGRESS",
            meta=_progress_meta(70, f"Subiendo a almacenamiento ({len(content) / 1024 / 1024:.1f} MB)…"),
        )

        gcs_path = upload_export_file(
            module="reporte_aptot",
            tenant_id=tenant_uuid,
            job_id=job_uuid,
            filename=filename,
            content=content,
        )
        download_url, expires_at = resolve_download_url(
            storage_path=gcs_path,
            filename=filename,
            job_id=job_uuid,
        )

        with SessionLocal() as db:
            row = dl_svc.get_descarga_archivo(db, job_uuid, tenant_uuid)
            if row is None:
                return {"success": False, "message": "Trabajo de descarga no encontrado"}
            dl_svc.mark_success(
                db,
                row,
                gcs_path=gcs_path,
                download_url=download_url,
                file_size_bytes=len(content),
                expires_at=expires_at,
            )
            db.commit()

        return {
            "success": True,
            "job_id": job_id,
            "filename": filename,
            "file_size_bytes": len(content),
            "download_url": download_url,
        }
    except Exception as exc:  # noqa: BLE001
        with SessionLocal() as db:
            row = dl_svc.get_descarga_archivo(db, job_uuid, tenant_uuid)
            if row is not None:
                dl_svc.mark_failure(db, row, message=str(exc)[:500])
                db.commit()
        return {"success": False, "job_id": job_id, "message": str(exc)}


@celery_app.task(bind=True, name="export.reporte_aptot_locales_csv")
def export_reporte_aptot_locales_csv_task(
    self,
    job_id: str,
    tenant_id: str,
    establishment_id: int,
) -> dict:
    job_uuid = UUID(job_id)
    tenant_uuid = UUID(tenant_id)

    try:
        with SessionLocal() as db:
            row = dl_svc.get_descarga_archivo(db, job_uuid, tenant_uuid)
            if row is None:
                return {"success": False, "message": "Trabajo de descarga no encontrado"}
            dl_svc.mark_processing(db, row)
            db.commit()
            filename = row.filename or f"reporte_aptot_locales_{establishment_id}_{date.today().isoformat()}.csv"

        self.update_state(state="PROGRESS", meta=_progress_meta(10, "Generando CSV…"))

        from app.modules.inventory.export_queries import build_reporte_aptot_locales_export_query

        inner_sql, params, _filename_base = build_reporte_aptot_locales_export_query(
            tenant_uuid,
            int(establishment_id),
        )
        payload = copy_query_to_csv_bytes(inner_sql, params)
        content = b"\xef\xbb\xbf" + payload

        self.update_state(
            state="PROGRESS",
            meta=_progress_meta(70, f"Subiendo a almacenamiento ({len(content) / 1024 / 1024:.1f} MB)…"),
        )

        gcs_path = upload_export_file(
            module="reporte_aptot_locales",
            tenant_id=tenant_uuid,
            job_id=job_uuid,
            filename=filename,
            content=content,
        )
        download_url, expires_at = resolve_download_url(
            storage_path=gcs_path,
            filename=filename,
            job_id=job_uuid,
        )

        with SessionLocal() as db:
            row = dl_svc.get_descarga_archivo(db, job_uuid, tenant_uuid)
            if row is None:
                return {"success": False, "message": "Trabajo de descarga no encontrado"}
            dl_svc.mark_success(
                db,
                row,
                gcs_path=gcs_path,
                download_url=download_url,
                file_size_bytes=len(content),
                expires_at=expires_at,
            )
            db.commit()

        return {
            "success": True,
            "job_id": job_id,
            "filename": filename,
            "file_size_bytes": len(content),
            "download_url": download_url,
        }
    except Exception as exc:  # noqa: BLE001
        with SessionLocal() as db:
            row = dl_svc.get_descarga_archivo(db, job_uuid, tenant_uuid)
            if row is not None:
                dl_svc.mark_failure(db, row, message=str(exc)[:500])
                db.commit()
        return {"success": False, "job_id": job_id, "message": str(exc)}


@celery_app.task(bind=True, name="export.item_cards_csv")
def export_item_cards_csv_task(
    self,
    job_id: str,
    tenant_id: str,
    query_dict: dict,
    export_format: str = "csv",
) -> dict:
    job_uuid = UUID(job_id)
    tenant_uuid = UUID(tenant_id)
    q = RecordQuery.model_validate(query_dict)
    fmt = (export_format or "csv").strip().lower()
    if fmt not in ("csv", "xlsx"):
        fmt = "csv"

    try:
        with SessionLocal() as db:
            row = dl_svc.get_descarga_archivo(db, job_uuid, tenant_uuid)
            if row is None:
                return {"success": False, "message": "Trabajo de descarga no encontrado"}
            dl_svc.mark_processing(
                db,
                row,
                message="Generando Excel…" if fmt == "xlsx" else "Generando CSV…",
            )
            db.commit()

        self.update_state(
            state="PROGRESS",
            meta=_progress_meta(10, "Generando Excel…" if fmt == "xlsx" else "Generando CSV…"),
        )

        inner_sql, params, filename_base = build_item_cards_export_query(tenant_uuid, q)
        stamp = date.today().isoformat()
        ext = "xlsx" if fmt == "xlsx" else "csv"
        filename = f"{filename_base}_{stamp}.{ext}"
        payload = copy_query_to_csv_bytes(inner_sql, params)
        if fmt == "xlsx":
            self.update_state(state="PROGRESS", meta=_progress_meta(45, "Convirtiendo a Excel…"))
            content = csv_bytes_to_xlsx_bytes(payload)
        else:
            content = b"\xef\xbb\xbf" + payload

        self.update_state(
            state="PROGRESS",
            meta=_progress_meta(70, f"Subiendo a almacenamiento ({len(content) / 1024 / 1024:.1f} MB)…"),
        )

        gcs_path = upload_export_file(
            module="item_cards",
            tenant_id=tenant_uuid,
            job_id=job_uuid,
            filename=filename,
            content=content,
        )
        download_url, expires_at = resolve_download_url(
            storage_path=gcs_path,
            filename=filename,
            job_id=job_uuid,
        )

        with SessionLocal() as db:
            row = dl_svc.get_descarga_archivo(db, job_uuid, tenant_uuid)
            if row is None:
                return {"success": False, "message": "Trabajo de descarga no encontrado"}
            dl_svc.mark_success(
                db,
                row,
                gcs_path=gcs_path,
                download_url=download_url,
                file_size_bytes=len(content),
                expires_at=expires_at,
            )
            db.commit()

        return {
            "success": True,
            "job_id": job_id,
            "filename": filename,
            "file_size_bytes": len(content),
            "download_url": download_url,
        }
    except Exception as exc:  # noqa: BLE001
        with SessionLocal() as db:
            row = dl_svc.get_descarga_archivo(db, job_uuid, tenant_uuid)
            if row is not None:
                dl_svc.mark_failure(db, row, message=str(exc)[:500])
                db.commit()
        return {"success": False, "job_id": job_id, "message": str(exc)}
