"""Persistencia de exportaciones CSV asíncronas (``descarga_archivos``)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date, datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.export_storage import refresh_download_url_if_needed
from app.modules.inventory.models import InvDescargaArchivo


def create_descarga_archivo(
    db: Session,
    *,
    job_id: UUID,
    tenant_id: UUID,
    module: str,
    filename: str,
    created_by_id: UUID | None = None,
    request_key: str | None = None,
) -> InvDescargaArchivo:
    row = InvDescargaArchivo(
        id=job_id,
        tenant_id=tenant_id,
        module=module,
        filename=filename,
        state="pending",
        progress=0,
        message="En cola…",
        created_by_id=created_by_id,
        request_key=request_key,
    )
    db.add(row)
    db.flush()
    return row


def set_celery_task_id(db: Session, row: InvDescargaArchivo, celery_task_id: str) -> None:
    row.celery_task_id = celery_task_id
    db.add(row)


def get_descarga_archivo(db: Session, job_id: UUID, tenant_id: UUID) -> InvDescargaArchivo | None:
    row = db.get(InvDescargaArchivo, job_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    return row


def mark_processing(db: Session, row: InvDescargaArchivo, *, message: str = "Generando CSV…") -> None:
    row.state = "processing"
    row.progress = max(row.progress, 5)
    row.message = message
    db.add(row)


def update_progress(db: Session, row: InvDescargaArchivo, *, progress: int, message: str) -> None:
    row.state = "processing"
    row.progress = progress
    row.message = message
    db.add(row)


def mark_success(
    db: Session,
    row: InvDescargaArchivo,
    *,
    gcs_path: str,
    download_url: str,
    file_size_bytes: int,
    expires_at,
    message: str = "Archivo listo para descarga",
) -> None:
    row.state = "success"
    row.progress = 100
    row.gcs_path = gcs_path
    row.download_url = download_url
    row.file_size_bytes = file_size_bytes
    row.expires_at = expires_at
    row.message = message
    row.errors = []
    db.add(row)


def mark_failure(db: Session, row: InvDescargaArchivo, *, message: str, errors: list[str] | None = None) -> None:
    row.state = "failure"
    row.progress = 0
    row.message = message
    row.errors = errors or [message]
    db.add(row)


def job_to_status_payload(db: Session, row: InvDescargaArchivo) -> dict[str, Any]:
    download_url = row.download_url
    expires_at = row.expires_at
    if row.state == "success" and row.gcs_path:
        download_url, expires_at = refresh_download_url_if_needed(
            storage_path=row.gcs_path,
            filename=row.filename,
            job_id=row.id,
            current_url=download_url,
            expires_at=expires_at,
        )
        if download_url != row.download_url or expires_at != row.expires_at:
            row.download_url = download_url
            row.expires_at = expires_at
            db.add(row)
            db.commit()

    return {
        "job_id": str(row.id),
        "module": row.module,
        "state": row.state,
        "progress": int(row.progress or 0),
        "filename": row.filename,
        "file_size_bytes": int(row.file_size_bytes or 0) if row.file_size_bytes else None,
        "download_url": download_url,
        "expires_at": expires_at.isoformat() if expires_at else None,
        "errors": list(row.errors or []),
        "message": row.message or "",
    }


def build_export_request_key(module: str, tenant_id: UUID, payload: dict[str, Any]) -> str:
    """Clave estable por módulo + tenant + parámetros que definen el archivo."""
    data = {"tenant_id": str(tenant_id), "module": module, **payload}
    raw = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _normalize_export_format(export_format: str | None) -> str:
    fmt = (export_format or "csv").strip().lower()
    return fmt if fmt in ("csv", "xlsx") else "csv"


def record_query_export_payload(q, *, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Filtros de listado que afectan exportaciones basadas en ``RecordQuery``."""
    payload: dict[str, Any] = {
        "search": (getattr(q, "search", None) or "").strip().lower() or None,
        "value": (getattr(q, "value", None) or "").strip().lower() or None,
        "column": (getattr(q, "column", None) or "").strip().lower() or None,
        "inv_sit_filter": getattr(q, "inv_sit_filter", None) or None,
        "local_code": (getattr(q, "local_code", None) or "").strip().upper() or None,
        "establishment_id": getattr(q, "establishment_id", None),
        "flag_firma": getattr(q, "flag_firma", None),
    }
    if extra:
        payload.update(extra)
    return payload


def build_margesi_export_request_key(tenant_id: UUID, q, export_format: str) -> str:
    fmt = _normalize_export_format(export_format)
    layout = (getattr(q, "export_layout", None) or "full").strip().lower()
    if layout not in ("full", "report"):
        layout = "full"
    return build_export_request_key(
        "margesi",
        tenant_id,
        record_query_export_payload(q, extra={"export_format": fmt, "export_layout": layout}),
    )


def find_reusable_descarga(
    db: Session,
    *,
    tenant_id: UUID,
    module: str,
    request_key: str,
    include_success: bool = True,
) -> InvDescargaArchivo | None:
    """Devuelve job activo (pending/processing) o success vigente con la misma request_key."""
    active = db.scalar(
        select(InvDescargaArchivo)
        .where(
            InvDescargaArchivo.tenant_id == tenant_id,
            InvDescargaArchivo.module == module,
            InvDescargaArchivo.request_key == request_key,
            InvDescargaArchivo.state.in_(("pending", "processing")),
        )
        .order_by(InvDescargaArchivo.created_at.desc())
        .limit(1)
    )
    if active is not None:
        return active
    if not include_success:
        return None
    now = datetime.now(timezone.utc)
    return db.scalar(
        select(InvDescargaArchivo)
        .where(
            InvDescargaArchivo.tenant_id == tenant_id,
            InvDescargaArchivo.module == module,
            InvDescargaArchivo.request_key == request_key,
            InvDescargaArchivo.state == "success",
            (InvDescargaArchivo.expires_at.is_(None)) | (InvDescargaArchivo.expires_at > now),
        )
        .order_by(InvDescargaArchivo.created_at.desc())
        .limit(1)
    )


def _advisory_lock(db: Session, tenant_id: UUID, module: str, request_key: str) -> None:
    lock_seed = int(hashlib.sha256(f"{tenant_id}:{module}:{request_key}".encode()).hexdigest()[:15], 16)
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": lock_seed % (2**31 - 1)})


def enqueue_shared_export(
    db: Session,
    *,
    tenant_id: UUID,
    module: str,
    request_key: str,
    filename: str,
    created_by_id: UUID | None,
    label: str,
    enqueue_celery,
) -> dict[str, Any]:
    """Reutiliza job activo/success vigente o crea uno nuevo y encola Celery.

    ``enqueue_celery(job_id: UUID) -> celery AsyncResult`` (o cualquier objeto con ``.id``).
    """
    _advisory_lock(db, tenant_id, module, request_key)
    existing = find_reusable_descarga(
        db,
        tenant_id=tenant_id,
        module=module,
        request_key=request_key,
    )
    if existing is not None:
        if existing.state in ("pending", "processing"):
            msg = (
                f"Ya hay una exportación {label} en curso. "
                "Se muestra el progreso compartido; no se genera de nuevo."
            )
        else:
            msg = (
                f"Se reutiliza la exportación {label} ya generada. "
                "Consulte el estado para descargar el mismo archivo."
            )
        return {
            "success": True,
            "async_job": True,
            "job_id": str(existing.id),
            "message": msg,
            "reused": True,
        }

    job_id = uuid.uuid4()
    row = create_descarga_archivo(
        db,
        job_id=job_id,
        tenant_id=tenant_id,
        module=module,
        filename=filename,
        created_by_id=created_by_id,
        request_key=request_key,
    )
    db.commit()

    task = enqueue_celery(job_id)
    set_celery_task_id(db, row, task.id)
    db.commit()

    return {
        "success": True,
        "async_job": True,
        "job_id": str(job_id),
        "message": f"Exportación {label} encolada. Consulte el estado para obtener el enlace de descarga.",
        "reused": False,
    }


def get_shared_export_meta(
    db: Session,
    *,
    tenant_id: UUID,
    module: str,
    request_key: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base: dict[str, Any] = {
        "status": "none",
        "job_id": None,
        "progress": 0,
        "message": "No hay exportación en curso ni archivo listo para estos parámetros.",
        "filename": None,
        "download_url": None,
        "file_size_bytes": None,
        "generated_at": None,
        "expires_at": None,
        "reused_available": False,
        **(extra or {}),
    }
    job = find_reusable_descarga(
        db,
        tenant_id=tenant_id,
        module=module,
        request_key=request_key,
        include_success=True,
    )
    if job is None:
        return base

    payload = job_to_status_payload(db, job)
    generated_at = job.updated_at if job.state == "success" else job.created_at
    return {
        **base,
        "status": payload["state"],
        "job_id": payload["job_id"],
        "progress": payload["progress"],
        "message": payload["message"],
        "filename": payload["filename"],
        "download_url": payload["download_url"] if job.state == "success" else None,
        "file_size_bytes": payload["file_size_bytes"],
        "generated_at": generated_at.isoformat() if generated_at else None,
        "expires_at": payload["expires_at"],
        "reused_available": True,
    }


def schedule_reporte_aptot_export(
    db: Session,
    *,
    tenant_id: UUID,
    export_format: str = "csv",
    created_by_id: UUID | None = None,
) -> dict[str, Any]:
    from app.tasks.csv_exports import export_reporte_aptot_csv_task

    fmt = _normalize_export_format(export_format)
    ext = "xlsx" if fmt == "xlsx" else "csv"
    request_key = build_export_request_key(
        "reporte_aptot",
        tenant_id,
        {"export_format": fmt},
    )
    label = "APTOT Excel" if fmt == "xlsx" else "APTOT CSV"
    return enqueue_shared_export(
        db,
        tenant_id=tenant_id,
        module="reporte_aptot",
        request_key=request_key,
        filename=f"reporte_aptot_export_{date.today().isoformat()}.{ext}",
        created_by_id=created_by_id,
        label=label,
        enqueue_celery=lambda job_id: export_reporte_aptot_csv_task.delay(str(job_id), str(tenant_id), fmt),
    )


def get_reporte_aptot_export_meta(
    db: Session,
    *,
    tenant_id: UUID,
    export_format: str = "csv",
) -> dict[str, Any]:
    fmt = _normalize_export_format(export_format)
    request_key = build_export_request_key("reporte_aptot", tenant_id, {"export_format": fmt})
    return get_shared_export_meta(
        db,
        tenant_id=tenant_id,
        module="reporte_aptot",
        request_key=request_key,
        extra={"export_format": fmt},
    )


def schedule_reporte_aptot_locales_export(
    db: Session,
    *,
    tenant_id: UUID,
    establishment_id: int,
    export_format: str = "csv",
    created_by_id: UUID | None = None,
) -> dict[str, Any]:
    from app.modules.inventory import models as m
    from app.tasks.csv_exports import export_reporte_aptot_locales_csv_task

    est = db.get(m.InvEstablishment, establishment_id)
    if not est or est.tenant_id != tenant_id:
        raise ValueError("Local no encontrado")

    fmt = _normalize_export_format(export_format)
    ext = "xlsx" if fmt == "xlsx" else "csv"
    code = str(est.code or establishment_id).strip() or str(establishment_id)
    request_key = build_export_request_key(
        "reporte_aptot_locales",
        tenant_id,
        {"establishment_id": int(establishment_id), "export_format": fmt},
    )
    label = f"APTOT local ({ 'Excel' if fmt == 'xlsx' else 'CSV' })"
    return enqueue_shared_export(
        db,
        tenant_id=tenant_id,
        module="reporte_aptot_locales",
        request_key=request_key,
        filename=f"reporte_aptot_locales_{establishment_id}_{code}_{date.today().isoformat()}.{ext}",
        created_by_id=created_by_id,
        label=label,
        enqueue_celery=lambda job_id: export_reporte_aptot_locales_csv_task.delay(
            str(job_id),
            str(tenant_id),
            int(establishment_id),
            fmt,
        ),
    )


def schedule_item_cards_export(
    db: Session,
    *,
    tenant_id: UUID,
    q,
    export_format: str = "csv",
    created_by_id: UUID | None = None,
) -> dict[str, Any]:
    from app.tasks.csv_exports import export_item_cards_csv_task

    fmt = _normalize_export_format(export_format)
    ext = "xlsx" if fmt == "xlsx" else "csv"
    request_key = build_export_request_key(
        "item_cards",
        tenant_id,
        record_query_export_payload(q, extra={"export_format": fmt}),
    )
    query_dict = q.model_dump(mode="json")
    label = "bienes Excel" if fmt == "xlsx" else "bienes CSV"
    return enqueue_shared_export(
        db,
        tenant_id=tenant_id,
        module="item_cards",
        request_key=request_key,
        filename=f"bienes_inventariados_export_{date.today().isoformat()}.{ext}",
        created_by_id=created_by_id,
        label=label,
        enqueue_celery=lambda job_id: export_item_cards_csv_task.delay(
            str(job_id), str(tenant_id), query_dict, fmt
        ),
    )


def get_item_cards_export_meta(
    db: Session,
    *,
    tenant_id: UUID,
    q,
    export_format: str = "csv",
) -> dict[str, Any]:
    fmt = _normalize_export_format(export_format)
    request_key = build_export_request_key(
        "item_cards",
        tenant_id,
        record_query_export_payload(q, extra={"export_format": fmt}),
    )
    return get_shared_export_meta(
        db,
        tenant_id=tenant_id,
        module="item_cards",
        request_key=request_key,
        extra={"export_format": fmt},
    )


def schedule_margesi_export(
    db: Session,
    *,
    tenant_id: UUID,
    q,
    export_format: str = "csv",
    created_by_id: UUID | None = None,
) -> dict[str, Any]:
    from app.tasks.csv_exports import export_margesi_csv_task

    fmt = _normalize_export_format(export_format)
    layout = (getattr(q, "export_layout", None) or "full").strip().lower()
    if layout not in ("full", "report"):
        layout = "full"
    base = "margesi_reporte" if layout == "report" else "margesi_export"
    ext = "xlsx" if fmt == "xlsx" else "csv"
    request_key = build_margesi_export_request_key(tenant_id, q, fmt)
    query_dict = q.model_dump(mode="json")
    label = "Margesi Excel" if fmt == "xlsx" else "Margesi CSV"
    return enqueue_shared_export(
        db,
        tenant_id=tenant_id,
        module="margesi",
        request_key=request_key,
        filename=f"{base}_{date.today().isoformat()}.{ext}",
        created_by_id=created_by_id,
        label=label,
        enqueue_celery=lambda job_id: export_margesi_csv_task.delay(
            str(job_id), str(tenant_id), query_dict, fmt
        ),
    )


def get_margesi_export_meta(
    db: Session,
    *,
    tenant_id: UUID,
    q,
    export_format: str = "csv",
) -> dict[str, Any]:
    fmt = _normalize_export_format(export_format)
    layout = (getattr(q, "export_layout", None) or "full").strip().lower()
    if layout not in ("full", "report"):
        layout = "full"
    request_key = build_margesi_export_request_key(tenant_id, q, fmt)
    return get_shared_export_meta(
        db,
        tenant_id=tenant_id,
        module="margesi",
        request_key=request_key,
        extra={"export_format": fmt, "export_layout": layout},
    )


def schedule_hoja_captura_export(
    db: Session,
    *,
    tenant_id: UUID,
    q,
    created_by_id: UUID | None = None,
) -> dict[str, Any]:
    from app.tasks.csv_exports import export_hoja_captura_task

    request_key = build_export_request_key(
        "hoja_captura",
        tenant_id,
        record_query_export_payload(q),
    )
    query_dict = q.model_dump(mode="json")
    return enqueue_shared_export(
        db,
        tenant_id=tenant_id,
        module="hoja_captura",
        request_key=request_key,
        filename=f"hoja_captura_export_{date.today().isoformat()}.xlsx",
        created_by_id=created_by_id,
        label="hoja de captura Excel",
        enqueue_celery=lambda job_id: export_hoja_captura_task.delay(
            str(job_id), str(tenant_id), query_dict
        ),
    )


def get_hoja_captura_export_meta(
    db: Session,
    *,
    tenant_id: UUID,
    q,
) -> dict[str, Any]:
    request_key = build_export_request_key(
        "hoja_captura",
        tenant_id,
        record_query_export_payload(q),
    )
    return get_shared_export_meta(
        db,
        tenant_id=tenant_id,
        module="hoja_captura",
        request_key=request_key,
    )


def get_descarga_archivo_status(db: Session, job_id: UUID, tenant_id: UUID) -> dict[str, Any]:
    row = get_descarga_archivo(db, job_id, tenant_id)
    if row is None:
        raise LookupError("Trabajo de descarga no encontrado")
    return job_to_status_payload(db, row)
