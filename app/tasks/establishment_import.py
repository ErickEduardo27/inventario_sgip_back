"""Tarea Celery: importación masiva de locales."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from app.celery_app import celery_app
from app.db.session import SessionLocal
from app.modules.inventory.establishment_import import process_establishment_upload


@celery_app.task(bind=True, name="establishments.import_bulk")
def import_establishments_task(self, tenant_id: str, file_path: str, filename: str) -> dict:
    path = Path(file_path)
    try:
        content = path.read_bytes()
        with SessionLocal() as db:
            def progress_cb(percent: int, total: int, updated: int, inserted: int) -> None:
                self.update_state(
                    state="PROGRESS",
                    meta={
                        "progress": percent,
                        "total_rows": total,
                        "processed": int(total * percent / 100),
                        "inserted": inserted,
                        "updated": updated,
                        "message": f"Procesando {percent}%…",
                    },
                )

            return process_establishment_upload(
                db,
                UUID(tenant_id),
                content,
                filename,
                progress_cb=progress_cb,
            )
    finally:
        if path.exists():
            path.unlink(missing_ok=True)
