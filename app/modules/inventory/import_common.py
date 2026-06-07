"""Utilidades compartidas para importación masiva (archivo → temp → Celery → COPY)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import pandas as pd

# Las importaciones masivas siempre se encolan en Celery (background).
ASYNC_IMPORT_THRESHOLD = 0


def save_upload_temp(content: bytes, filename: str, *, prefix: str = "import_") -> Path:
    suffix = Path(filename).suffix or ".xlsx"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix=prefix)
    try:
        tmp.write(content)
        tmp.flush()
        return Path(tmp.name)
    finally:
        tmp.close()


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
    import io

    lower = filename.lower()
    if lower.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        raw = pd.read_csv(io.StringIO(text), header=None, dtype=str, keep_default_na=False)
    elif lower.endswith((".xlsx", ".xls")):
        raw = pd.read_excel(io.BytesIO(content), header=None, dtype=str, keep_default_na=False)
    else:
        return 0
    return max(0, int(len(raw)) - 1)


def celery_import_job_status(job_id: str) -> dict[str, Any]:
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


def dispatch_sync_or_celery(
    *,
    content: bytes,
    filename: str,
    tenant_id,
    db,
    row_count: int,
    temp_prefix: str,
    celery_task,
    sync_processor,
    celery_args: tuple = (),
    sync_kwargs: dict | None = None,
) -> dict[str, Any]:
    """Guarda el archivo y encola siempre la importación en Celery."""
    del db, sync_processor, sync_kwargs  # procesamiento solo en el worker
    temp_path = save_upload_temp(content, filename, prefix=temp_prefix)
    task = celery_task.delay(str(tenant_id), str(temp_path), filename, *celery_args)
    return make_async_response(task_id=task.id, row_count=row_count)


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
