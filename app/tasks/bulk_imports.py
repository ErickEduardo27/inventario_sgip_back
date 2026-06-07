"""Tareas Celery: importación masiva por módulo (archivo temporal → COPY)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.modules.inventory import (
    cost_center_import,
    environment_import,
    establishment_import,
    list_sbn_import,
    margesi_import,
    person_import,
)


def _progress_meta(
    percent: int,
    total: int,
    updated: int,
    inserted: int,
    *,
    registered: int | None = None,
    errors: list[str] | None = None,
    message: str | None = None,
) -> dict[str, Any]:
    return {
        "progress": percent,
        "total_rows": total,
        "processed": int(total * percent / 100),
        "inserted": inserted,
        "updated": updated,
        "registered": registered if registered is not None else inserted + updated,
        "errors": errors or [],
        "message": message or f"Procesando {percent}%…",
    }


def _run_file_import(
    task,
    *,
    tenant_id: str,
    file_path: str,
    filename: str,
    processor: Callable[..., dict[str, Any]],
    extra_kwargs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    path = Path(file_path)
    extra_kwargs = extra_kwargs or {}
    try:
        content = path.read_bytes()
        task.update_state(
            state="PROGRESS",
            meta=_progress_meta(1, 0, 0, 0, message="Leyendo archivo…"),
        )
        with SessionLocal() as db:

            def progress_cb(percent: int, total: int, updated: int, inserted: int) -> None:
                task.update_state(
                    state="PROGRESS",
                    meta=_progress_meta(percent, total, updated, inserted),
                )

            return processor(
                db,
                UUID(tenant_id),
                content,
                filename,
                progress_cb=progress_cb,
                **extra_kwargs,
            )
    finally:
        if path.exists():
            path.unlink(missing_ok=True)


@celery_app.task(bind=True, name="imports.establishments")
def import_establishments_task(self, tenant_id: str, file_path: str, filename: str) -> dict:
    return _run_file_import(
        self,
        tenant_id=tenant_id,
        file_path=file_path,
        filename=filename,
        processor=establishment_import.process_establishment_upload,
    )


@celery_app.task(bind=True, name="imports.environments")
def import_environments_task(self, tenant_id: str, file_path: str, filename: str) -> dict:
    return _run_file_import(
        self,
        tenant_id=tenant_id,
        file_path=file_path,
        filename=filename,
        processor=environment_import.process_environment_upload,
    )


@celery_app.task(bind=True, name="imports.cost_centers")
def import_cost_centers_task(self, tenant_id: str, file_path: str, filename: str) -> dict:
    return _run_file_import(
        self,
        tenant_id=tenant_id,
        file_path=file_path,
        filename=filename,
        processor=cost_center_import.process_cost_center_upload,
    )


@celery_app.task(bind=True, name="imports.persons")
def import_persons_task(self, tenant_id: str, file_path: str, filename: str, person_type: str) -> dict:
    return _run_file_import(
        self,
        tenant_id=tenant_id,
        file_path=file_path,
        filename=filename,
        processor=person_import.process_person_upload,
        extra_kwargs={"person_type": person_type},
    )


@celery_app.task(bind=True, name="imports.list_sbn")
def import_list_sbn_task(self, tenant_id: str, file_path: str, filename: str) -> dict:
    return _run_file_import(
        self,
        tenant_id=tenant_id,
        file_path=file_path,
        filename=filename,
        processor=list_sbn_import.process_list_sbn_upload,
    )


@celery_app.task(bind=True, name="imports.margesi")
def import_margesi_task(self, tenant_id: str, file_path: str, filename: str) -> dict:
    return _run_file_import(
        self,
        tenant_id=tenant_id,
        file_path=file_path,
        filename=filename,
        processor=margesi_import.process_margesi_upload,
    )


@celery_app.task(bind=True, name="imports.margesi_moment")
def import_margesi_moment_task(self, tenant_id: str, file_path: str, filename: str) -> dict:
    return _run_file_import(
        self,
        tenant_id=tenant_id,
        file_path=file_path,
        filename=filename,
        processor=margesi_import.process_margesi_moment_upload,
    )
