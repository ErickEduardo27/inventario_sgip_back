"""Utilidades compartidas para importación masiva (GCS → import_jobs → Celery → COPY)."""

from __future__ import annotations

import io
import uuid
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy.orm import Session

from app.core.import_storage import upload_import_file
from app.modules.inventory import import_jobs_service as jobs_svc

# Módulos con importación masiva vía GCS + import_jobs + Celery.
IMPORT_MODULE_ESTABLISHMENTS = "establishments"
IMPORT_MODULE_PERSONS = "persons"
IMPORT_MODULE_COST_CENTERS = "cost_centers"
IMPORT_MODULE_ENVIRONMENTS = "environments"
IMPORT_MODULE_LIST_SBN = "list_sbn"
IMPORT_MODULE_MARGESI = "margesi"
IMPORT_MODULE_MARGESI_MOMENT = "margesi_moment"
IMPORT_MODULE_HOJA_CAPTURA = "hoja_captura"
IMPORT_MODULE_CARDS = "cards"

# Las importaciones masivas siempre se encolan en Celery (background).
ASYNC_IMPORT_THRESHOLD = 0


def count_data_rows(content: bytes, filename: str) -> int:
    """Cuenta filas de datos (excluye cabecera)."""
    from app.modules.inventory.establishment_import import parse_establishment_upload

    try:
        df = parse_establishment_upload(content, filename)
        return int(len(df))
    except ValueError:
        return 0


def count_data_rows_raw(content: bytes, filename: str) -> int:
    """Cuenta filas de datos leyendo solo el archivo (sin validar columnas)."""
    lower = filename.lower()
    if lower.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        raw = pd.read_csv(io.StringIO(text), header=None, dtype=str, keep_default_na=False)
    elif lower.endswith((".xlsx", ".xls")):
        raw = pd.read_excel(io.BytesIO(content), header=None, dtype=str, keep_default_na=False)
    else:
        return 0
    return max(0, int(len(raw)) - 1)


def get_import_job_status(db: Session, job_id: UUID, tenant_id: UUID) -> dict[str, Any]:
    job = jobs_svc.get_import_job(db, job_id, tenant_id)
    if job is None:
        raise LookupError("Trabajo de importación no encontrado")
    return jobs_svc.job_to_status_payload(job)


def celery_import_job_status(job_id: str) -> dict[str, Any]:
    """Compatibilidad: estado desde Celery/Redis (jobs antiguos sin fila en BD)."""
    from celery.result import AsyncResult

    from app.celery_app import celery_app

    result = AsyncResult(job_id, app=celery_app)
    state = result.state or "PENDING"

    if state == "PENDING":
        return {
            "job_id": job_id,
            "state": "pending",
            "progress": 0,
            "message": "En cola… (¿worker Celery activo?)",
            "total_rows": 0,
            "processed": 0,
            "inserted": 0,
            "updated": 0,
            "registered": 0,
            "errors": [],
        }
    if state in ("STARTED", "RECEIVED"):
        return {
            "job_id": job_id,
            "state": "processing",
            "progress": 2,
            "message": "Procesando archivo…",
            "total_rows": 0,
            "processed": 0,
            "inserted": 0,
            "updated": 0,
            "registered": 0,
            "errors": [],
        }
    if state == "PROGRESS":
        meta = result.info if isinstance(result.info, dict) else {}
        return {
            "job_id": job_id,
            "state": "processing",
            "progress": int(meta.get("progress") or 0),
            "total_rows": int(meta.get("total_rows") or 0),
            "processed": int(meta.get("processed") or 0),
            "inserted": int(meta.get("inserted") or 0),
            "updated": int(meta.get("updated") or 0),
            "registered": int(meta.get("registered") or 0),
            "errors": list(meta.get("errors") or []),
            "message": str(meta.get("message") or "Procesando…"),
        }
    if result.state == "SUCCESS":
        payload = result.result if isinstance(result.result, dict) else {}
        total = int(
            payload.get("total_rows")
            or payload.get("total")
            or payload.get("registered")
            or 0
        )
        inserted = int(payload.get("inserted") or 0)
        updated = int(payload.get("updated") or 0)
        registered = int(payload.get("registered") or inserted + updated or total)
        return {
            "job_id": job_id,
            "state": "success",
            "progress": 100,
            "total_rows": total,
            "processed": total,
            "inserted": inserted,
            "updated": updated,
            "registered": registered,
            "errors": list(payload.get("errors") or []),
            "message": str(payload.get("message") or "Importación completada"),
        }
    meta = result.info if isinstance(result.info, dict) else {}
    err = meta.get("message") if isinstance(meta, dict) else str(result.info)
    return {
        "job_id": job_id,
        "state": "failure",
        "progress": 0,
        "total_rows": 0,
        "processed": 0,
        "inserted": 0,
        "updated": 0,
        "registered": 0,
        "errors": [str(err or "Error en la importación")],
        "message": "La importación falló",
    }


async def read_upload_bytes(file) -> tuple[bytes, str]:
    filename = file.filename or "upload.xlsx"
    lower = filename.lower()
    if not lower.endswith((".xlsx", ".xls", ".csv")):
        raise ValueError("Formato no soportado. Use .xlsx, .xls o .csv")
    content = await file.read()
    if not content:
        raise ValueError("Archivo vacío")
    return content, filename


def dispatch_import_job(
    *,
    db: Session,
    content: bytes,
    filename: str,
    tenant_id: UUID,
    module: str,
    row_count: int,
    celery_task,
    celery_args: tuple = (),
    created_by_id: UUID | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Sube a GCS, crea ``import_jobs`` y encola Celery con ``job_id`` + ``gcs_path``."""
    job_id = uuid.uuid4()
    gcs_path = upload_import_file(
        module=module,
        tenant_id=tenant_id,
        job_id=job_id,
        filename=filename,
        content=content,
    )

    job = jobs_svc.create_import_job(
        db,
        job_id=job_id,
        tenant_id=tenant_id,
        module=module,
        filename=filename,
        gcs_path=gcs_path,
        total_rows=row_count,
        created_by_id=created_by_id,
        extra=extra,
    )
    db.commit()

    task = celery_task.delay(str(job_id), str(tenant_id), gcs_path, filename, *celery_args)
    jobs_svc.set_celery_task_id(db, job, task.id)
    db.commit()

    return make_async_response(task_id=str(job_id), row_count=row_count)


def dispatch_sync_or_celery(
    *,
    content: bytes,
    filename: str,
    tenant_id,
    db: Session,
    row_count: int,
    temp_prefix: str,
    celery_task,
    sync_processor,
    celery_args: tuple = (),
    sync_kwargs: dict | None = None,
    module: str | None = None,
    created_by_id: UUID | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    del temp_prefix, sync_processor, sync_kwargs
    if module is None:
        raise ValueError("module es obligatorio para dispatch_import_job")
    return dispatch_import_job(
        db=db,
        content=content,
        filename=filename,
        tenant_id=tenant_id,
        module=module,
        row_count=row_count,
        celery_task=celery_task,
        celery_args=celery_args,
        created_by_id=created_by_id,
        extra=extra,
    )


def make_async_response(
    *,
    task_id: str,
    row_count: int,
    message: str = "Importación iniciada en segundo plano.",
) -> dict[str, Any]:
    return {
        "success": True,
        "message": message,
        "total_rows": row_count,
        "total": row_count,
        "registered": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": [],
        "async_job": True,
        "job_id": task_id,
    }
