"""Persistencia de trabajos de importación masiva (`import_jobs`)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.modules.inventory.models import InvImportJob


def create_import_job(
    db: Session,
    *,
    job_id: UUID,
    tenant_id: UUID,
    module: str,
    filename: str,
    gcs_path: str,
    total_rows: int = 0,
    created_by_id: UUID | None = None,
    extra: dict[str, Any] | None = None,
) -> InvImportJob:
    job = InvImportJob(
        id=job_id,
        tenant_id=tenant_id,
        module=module,
        filename=filename,
        gcs_path=gcs_path,
        state="pending",
        progress=0,
        total_rows=total_rows,
        message="En cola…",
        created_by_id=created_by_id,
        extra=extra or {},
    )
    db.add(job)
    db.flush()
    return job


def set_celery_task_id(db: Session, job: InvImportJob, celery_task_id: str) -> None:
    job.celery_task_id = celery_task_id
    db.add(job)


def get_import_job(db: Session, job_id: UUID, tenant_id: UUID) -> InvImportJob | None:
    job = db.get(InvImportJob, job_id)
    if job is None or job.tenant_id != tenant_id:
        return None
    return job


def mark_processing(db: Session, job: InvImportJob) -> None:
    job.state = "processing"
    job.progress = max(job.progress, 2)
    job.message = "Descargando y procesando archivo…"
    db.add(job)


def update_progress(
    db: Session,
    job: InvImportJob,
    *,
    progress: int,
    total_rows: int,
    processed: int,
    inserted: int,
    updated: int,
    registered: int,
    message: str | None = None,
    errors: list[str] | None = None,
) -> None:
    job.state = "processing"
    job.progress = progress
    job.total_rows = total_rows
    job.processed = processed
    job.inserted = inserted
    job.updated = updated
    job.registered = registered
    if message:
        job.message = message
    if errors:
        job.errors = errors
    db.add(job)


def finalize_from_result(db: Session, job: InvImportJob, result: dict[str, Any]) -> None:
    success = bool(result.get("success"))
    total = int(result.get("total_rows") or result.get("total") or job.total_rows or 0)
    inserted = int(result.get("inserted") or 0)
    updated = int(result.get("updated") or 0)
    registered = int(result.get("registered") or inserted + updated or total)
    errors = list(result.get("errors") or [])

    job.total_rows = total or job.total_rows
    job.processed = total or job.processed
    job.inserted = inserted
    job.updated = updated
    job.registered = registered
    job.errors = errors

    if success:
        job.state = "success"
        job.progress = 100
        job.message = str(result.get("message") or "Importación completada")
    else:
        job.state = "failure"
        job.progress = 0
        job.message = str(result.get("message") or "La importación falló")
    db.add(job)


def mark_failure(db: Session, job: InvImportJob, *, message: str, errors: list[str] | None = None) -> None:
    job.state = "failure"
    job.progress = 0
    job.message = message
    job.errors = errors or [message]
    db.add(job)


def job_to_status_payload(job: InvImportJob) -> dict[str, Any]:
    return {
        "job_id": str(job.id),
        "state": job.state,
        "progress": int(job.progress or 0),
        "total_rows": int(job.total_rows or 0),
        "processed": int(job.processed or 0),
        "inserted": int(job.inserted or 0),
        "updated": int(job.updated or 0),
        "registered": int(job.registered or 0),
        "errors": list(job.errors or []),
        "message": job.message or "",
    }
