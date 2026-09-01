"""Persistencia de exportaciones CSV asíncronas (``descarga_archivos``)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any
from uuid import UUID

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


def schedule_reporte_aptot_export(
    db: Session,
    *,
    tenant_id: UUID,
    created_by_id: UUID | None = None,
) -> dict[str, Any]:
    from app.tasks.csv_exports import export_reporte_aptot_csv_task

    job_id = uuid.uuid4()
    filename = f"reporte_aptot_export_{date.today().isoformat()}.csv"
    row = create_descarga_archivo(
        db,
        job_id=job_id,
        tenant_id=tenant_id,
        module="reporte_aptot",
        filename=filename,
        created_by_id=created_by_id,
    )
    db.commit()

    task = export_reporte_aptot_csv_task.delay(str(job_id), str(tenant_id))
    set_celery_task_id(db, row, task.id)
    db.commit()

    return {
        "success": True,
        "async_job": True,
        "job_id": str(job_id),
        "message": "Exportación APTOT encolada. Consulte el estado para obtener el enlace de descarga.",
    }


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

    fmt = (export_format or "csv").strip().lower()
    if fmt not in ("csv", "xlsx"):
        fmt = "csv"
    ext = "xlsx" if fmt == "xlsx" else "csv"

    job_id = uuid.uuid4()
    code = str(est.code or establishment_id).strip() or str(establishment_id)
    filename = f"reporte_aptot_locales_{establishment_id}_{code}_{date.today().isoformat()}.{ext}"
    row = create_descarga_archivo(
        db,
        job_id=job_id,
        tenant_id=tenant_id,
        module="reporte_aptot_locales",
        filename=filename,
        created_by_id=created_by_id,
    )
    db.commit()

    task = export_reporte_aptot_locales_csv_task.delay(
        str(job_id),
        str(tenant_id),
        int(establishment_id),
        fmt,
    )
    set_celery_task_id(db, row, task.id)
    db.commit()

    label = "Excel" if fmt == "xlsx" else "CSV"
    return {
        "success": True,
        "async_job": True,
        "job_id": str(job_id),
        "message": f"Generación del reporte APTOT del local ({label}) encolada. Podrá descargarlo cuando finalice.",
    }


def schedule_item_cards_export(
    db: Session,
    *,
    tenant_id: UUID,
    q,
    export_format: str = "csv",
    created_by_id: UUID | None = None,
) -> dict[str, Any]:
    from app.tasks.csv_exports import export_item_cards_csv_task

    fmt = (export_format or "csv").strip().lower()
    if fmt not in ("csv", "xlsx"):
        fmt = "csv"

    job_id = uuid.uuid4()
    ext = "xlsx" if fmt == "xlsx" else "csv"
    filename = f"bienes_inventariados_export_{date.today().isoformat()}.{ext}"
    row = create_descarga_archivo(
        db,
        job_id=job_id,
        tenant_id=tenant_id,
        module="item_cards",
        filename=filename,
        created_by_id=created_by_id,
    )
    db.commit()

    query_dict = q.model_dump(mode="json")
    task = export_item_cards_csv_task.delay(str(job_id), str(tenant_id), query_dict, fmt)
    set_celery_task_id(db, row, task.id)
    db.commit()

    label = "Excel" if fmt == "xlsx" else "CSV"
    return {
        "success": True,
        "async_job": True,
        "job_id": str(job_id),
        "message": f"Exportación {label} de bienes encolada. Consulte el estado para obtener el enlace de descarga.",
    }


def schedule_margesi_export(
    db: Session,
    *,
    tenant_id: UUID,
    q,
    export_format: str = "csv",
    created_by_id: UUID | None = None,
) -> dict[str, Any]:
    from app.tasks.csv_exports import export_margesi_csv_task

    fmt = (export_format or "csv").strip().lower()
    if fmt not in ("csv", "xlsx"):
        fmt = "csv"

    layout = (getattr(q, "export_layout", None) or "full").strip().lower()
    if layout not in ("full", "report"):
        layout = "full"
    base = "margesi_reporte" if layout == "report" else "margesi_export"

    job_id = uuid.uuid4()
    ext = "xlsx" if fmt == "xlsx" else "csv"
    filename = f"{base}_{date.today().isoformat()}.{ext}"
    row = create_descarga_archivo(
        db,
        job_id=job_id,
        tenant_id=tenant_id,
        module="margesi",
        filename=filename,
        created_by_id=created_by_id,
    )
    db.commit()

    query_dict = q.model_dump(mode="json")
    task = export_margesi_csv_task.delay(str(job_id), str(tenant_id), query_dict, fmt)
    set_celery_task_id(db, row, task.id)
    db.commit()

    label = "Excel" if fmt == "xlsx" else "CSV"
    return {
        "success": True,
        "async_job": True,
        "job_id": str(job_id),
        "message": f"Exportación {label} de Margesi encolada. Consulte el estado para obtener el enlace de descarga.",
    }


def schedule_hoja_captura_export(
    db: Session,
    *,
    tenant_id: UUID,
    q,
    created_by_id: UUID | None = None,
) -> dict[str, Any]:
    from app.tasks.csv_exports import export_hoja_captura_task

    job_id = uuid.uuid4()
    filename = f"hoja_captura_export_{date.today().isoformat()}.xlsx"
    row = create_descarga_archivo(
        db,
        job_id=job_id,
        tenant_id=tenant_id,
        module="hoja_captura",
        filename=filename,
        created_by_id=created_by_id,
    )
    db.commit()

    query_dict = q.model_dump(mode="json")
    task = export_hoja_captura_task.delay(str(job_id), str(tenant_id), query_dict)
    set_celery_task_id(db, row, task.id)
    db.commit()

    return {
        "success": True,
        "async_job": True,
        "job_id": str(job_id),
        "message": "Exportación Excel encolada. Le avisaremos cuando el archivo esté listo para descargar.",
    }


def get_descarga_archivo_status(db: Session, job_id: UUID, tenant_id: UUID) -> dict[str, Any]:
    row = get_descarga_archivo(db, job_id, tenant_id)
    if row is None:
        raise LookupError("Trabajo de descarga no encontrado")
    return job_to_status_payload(db, row)
