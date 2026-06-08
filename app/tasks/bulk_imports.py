"""Tareas Celery: importación masiva por módulo (GCS → COPY → import_jobs)."""

from __future__ import annotations

from typing import Any, Callable
from uuid import UUID

from app.celery_app import celery_app
from app.core.import_storage import delete_import_file, download_import_file
from app.db.session import SessionLocal
from app.modules.inventory import (
    cards_import,
    cost_center_import,
    environment_import,
    establishment_import,
    hoja_captura_import,
    import_jobs_service as jobs_svc,
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


def _run_gcs_import(
    task,
    *,
    job_id: str,
    tenant_id: str,
    gcs_path: str,
    filename: str,
    processor: Callable[..., dict[str, Any]],
    extra_kwargs: dict[str, Any] | None = None,
    pass_operator_id: bool = False,
) -> dict[str, Any]:
    extra_kwargs = extra_kwargs or {}
    job_uuid = UUID(job_id)
    tenant_uuid = UUID(tenant_id)

    try:
        with SessionLocal() as db:
            job = jobs_svc.get_import_job(db, job_uuid, tenant_uuid)
            if job is None:
                return {
                    "success": False,
                    "message": "Trabajo de importación no encontrado",
                    "errors": ["import_jobs: registro inexistente"],
                }
            jobs_svc.mark_processing(db, job)
            db.commit()

        task.update_state(
            state="PROGRESS",
            meta=_progress_meta(1, 0, 0, 0, message="Descargando archivo…"),
        )
        content = download_import_file(gcs_path)

        with SessionLocal() as db:
            job = jobs_svc.get_import_job(db, job_uuid, tenant_uuid)
            if job is None:
                return {
                    "success": False,
                    "message": "Trabajo de importación no encontrado",
                    "errors": ["import_jobs: registro inexistente"],
                }

            def _persist_job_progress(meta: dict[str, Any]) -> None:
                task.update_state(state="PROGRESS", meta=meta)
                # Sesión aparte: no hacer commit sobre la conexión del COPY masivo.
                with SessionLocal() as progress_db:
                    progress_job = jobs_svc.get_import_job(progress_db, job_uuid, tenant_uuid)
                    if progress_job is None:
                        return
                    jobs_svc.update_progress(
                        progress_db,
                        progress_job,
                        progress=int(meta["progress"]),
                        total_rows=int(meta["total_rows"]),
                        processed=int(meta["processed"]),
                        inserted=int(meta["inserted"]),
                        updated=int(meta["updated"]),
                        registered=int(meta["registered"]),
                        message=str(meta["message"]),
                    )
                    progress_db.commit()

            def progress_cb(percent: int, total: int, updated: int, inserted: int) -> None:
                _persist_job_progress(_progress_meta(percent, total, updated, inserted))

            proc_kwargs = dict(extra_kwargs or {})
            if pass_operator_id and job.created_by_id is not None:
                proc_kwargs["operator_id"] = job.created_by_id

            result = processor(
                db,
                tenant_uuid,
                content,
                filename,
                progress_cb=progress_cb,
                **proc_kwargs,
            )

            job = jobs_svc.get_import_job(db, job_uuid, tenant_uuid)
            if job is not None:
                jobs_svc.finalize_from_result(db, job, result)
                db.commit()
            return result
    except Exception as exc:  # noqa: BLE001
        with SessionLocal() as db:
            job = jobs_svc.get_import_job(db, job_uuid, tenant_uuid)
            if job is not None:
                jobs_svc.mark_failure(db, job, message="Error en la importación", errors=[str(exc)])
                db.commit()
        return {
            "success": False,
            "message": "Error en la importación",
            "errors": [str(exc)],
        }
    finally:
        delete_import_file(gcs_path)


@celery_app.task(bind=True, name="imports.establishments")
def import_establishments_task(self, job_id: str, tenant_id: str, gcs_path: str, filename: str) -> dict:
    return _run_gcs_import(
        self,
        job_id=job_id,
        tenant_id=tenant_id,
        gcs_path=gcs_path,
        filename=filename,
        processor=establishment_import.process_establishment_upload,
    )


@celery_app.task(bind=True, name="imports.environments")
def import_environments_task(self, job_id: str, tenant_id: str, gcs_path: str, filename: str) -> dict:
    return _run_gcs_import(
        self,
        job_id=job_id,
        tenant_id=tenant_id,
        gcs_path=gcs_path,
        filename=filename,
        processor=environment_import.process_environment_upload,
    )


@celery_app.task(bind=True, name="imports.cost_centers")
def import_cost_centers_task(self, job_id: str, tenant_id: str, gcs_path: str, filename: str) -> dict:
    return _run_gcs_import(
        self,
        job_id=job_id,
        tenant_id=tenant_id,
        gcs_path=gcs_path,
        filename=filename,
        processor=cost_center_import.process_cost_center_upload,
    )


@celery_app.task(bind=True, name="imports.persons")
def import_persons_task(
    self,
    job_id: str,
    tenant_id: str,
    gcs_path: str,
    filename: str,
    person_type: str,
) -> dict:
    return _run_gcs_import(
        self,
        job_id=job_id,
        tenant_id=tenant_id,
        gcs_path=gcs_path,
        filename=filename,
        processor=person_import.process_person_upload,
        extra_kwargs={"person_type": person_type},
    )


@celery_app.task(bind=True, name="imports.list_sbn")
def import_list_sbn_task(self, job_id: str, tenant_id: str, gcs_path: str, filename: str) -> dict:
    return _run_gcs_import(
        self,
        job_id=job_id,
        tenant_id=tenant_id,
        gcs_path=gcs_path,
        filename=filename,
        processor=list_sbn_import.process_list_sbn_upload,
    )


@celery_app.task(bind=True, name="imports.margesi")
def import_margesi_task(self, job_id: str, tenant_id: str, gcs_path: str, filename: str) -> dict:
    return _run_gcs_import(
        self,
        job_id=job_id,
        tenant_id=tenant_id,
        gcs_path=gcs_path,
        filename=filename,
        processor=margesi_import.process_margesi_upload,
    )


@celery_app.task(bind=True, name="imports.margesi_moment")
def import_margesi_moment_task(self, job_id: str, tenant_id: str, gcs_path: str, filename: str) -> dict:
    return _run_gcs_import(
        self,
        job_id=job_id,
        tenant_id=tenant_id,
        gcs_path=gcs_path,
        filename=filename,
        processor=margesi_import.process_margesi_moment_upload,
    )


@celery_app.task(bind=True, name="imports.hoja_captura")
def import_hoja_captura_task(self, job_id: str, tenant_id: str, gcs_path: str, filename: str) -> dict:
    return _run_gcs_import(
        self,
        job_id=job_id,
        tenant_id=tenant_id,
        gcs_path=gcs_path,
        filename=filename,
        processor=hoja_captura_import.process_hoja_captura_upload,
        pass_operator_id=True,
    )


@celery_app.task(bind=True, name="imports.cards")
def import_cards_task(self, job_id: str, tenant_id: str, gcs_path: str, filename: str) -> dict:
    return _run_gcs_import(
        self,
        job_id=job_id,
        tenant_id=tenant_id,
        gcs_path=gcs_path,
        filename=filename,
        processor=cards_import.process_cards_upload,
        pass_operator_id=True,
    )
