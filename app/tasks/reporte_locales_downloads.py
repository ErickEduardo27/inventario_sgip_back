"""Tarea Celery: ZIP de fotos/PDF de Reporte Locales → GCS → descarga_archivos."""

from __future__ import annotations

import io
import zipfile
from typing import Any
from uuid import UUID

from app.celery_app import celery_app
from app.core.export_storage import resolve_download_url, upload_export_file
from app.db.session import SessionLocal
from app.modules.inventory import descarga_archivos_service as dl_svc
from app.modules.inventory import reporte_locales_download_service as rl_dl
from app.core.reporte_local_storage import read_reporte_local_file_bytes


def _progress_meta(progress: int, message: str) -> dict:
    return {"progress": progress, "message": message}


@celery_app.task(bind=True, name="export.reporte_locales_files_zip")
def export_reporte_locales_files_zip_task(
    self,
    job_id: str,
    tenant_id: str,
    filters: dict[str, Any],
) -> dict:
    job_uuid = UUID(job_id)
    tenant_uuid = UUID(tenant_id)

    try:
        with SessionLocal() as db:
            row = dl_svc.get_descarga_archivo(db, job_uuid, tenant_uuid)
            if row is None:
                return {"success": False, "message": "Trabajo de descarga no encontrado"}
            filename = row.filename
            dl_svc.mark_processing(db, row, message="Preparando archivos…")
            db.commit()

            items = rl_dl.collect_bulk_files(
                db,
                tenant_uuid,
                establishment_ids=filters.get("establishment_ids") or None,
                department_id=filters.get("department_id") or None,
                include_fotos=bool(filters.get("include_fotos", True)),
                include_pdfs=bool(filters.get("include_pdfs", True)),
            )

        total = len(items)
        self.update_state(state="PROGRESS", meta=_progress_meta(8, f"Empaquetando {total} archivo(s)…"))

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for idx, item in enumerate(items):
                data_mime = read_reporte_local_file_bytes(item.stored_url, tenant_uuid)
                if not data_mime:
                    continue
                data, _mime = data_mime
                zf.writestr(item.zip_path, data)
                pct = 8 + int(((idx + 1) / max(total, 1)) * 62)
                if (idx + 1) % 5 == 0 or idx + 1 == total:
                    self.update_state(
                        state="PROGRESS",
                        meta=_progress_meta(pct, f"Empaquetando {idx + 1}/{total}…"),
                    )

        content = buffer.getvalue()
        if not content:
            raise RuntimeError("No se pudo generar el ZIP")

        self.update_state(
            state="PROGRESS",
            meta=_progress_meta(75, f"Subiendo ZIP ({len(content) / 1024 / 1024:.1f} MB)…"),
        )

        gcs_path = upload_export_file(
            module="reporte_locales",
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
                message="ZIP listo para descarga",
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
