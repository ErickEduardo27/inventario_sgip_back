"""Descargas de fotos/PDF de Reporte Locales: URLs firmadas y ZIP asíncrono."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.reporte_local_storage import (
    generate_reporte_local_signed_url,
    read_reporte_local_file_bytes,
)
from app.modules.inventory import descarga_archivos_service as dl_svc
from app.modules.inventory import models as m

FileKindFilter = Literal["all", "fotos", "pdfs"]


@dataclass(frozen=True)
class BulkFileItem:
    establishment_id: int
    establishment_code: str
    establishment_description: str | None
    kind: str
    stored_url: str
    zip_path: str
    download_name: str


def _safe_filename(name: str, fallback: str) -> str:
    base = re.sub(r"[^\w.\-]+", "_", (name or "").strip()) or fallback
    return base[:120]


def _local_file_prefix(code: str, description: str | None) -> str:
    code_part = _safe_filename(str(code or "").strip(), "local")
    desc_part = _safe_filename((description or "").strip(), "")
    if desc_part and desc_part != "local":
        combined = f"{code_part}_{desc_part}"
    else:
        combined = code_part
    return combined[:80] or "local"


def _foto_download_name(code: str, description: str | None, index: int) -> str:
    prefix = _local_file_prefix(code, description)
    return f"{prefix}_foto_{index + 1:02d}.jpg"


def _pdf_download_name(code: str, description: str | None, index: int) -> str:
    prefix = _local_file_prefix(code, description)
    return f"{prefix}_pdf_{index + 1:02d}.pdf"


def _safe_folder_name(code: str, description: str | None) -> str:
    label = f"{code}_{(description or '').strip()}".strip("_")
    cleaned = re.sub(r"[^\w\s.\-]+", "_", label).strip()
    return (cleaned[:80] or code or "local").strip()


def _normalize_url_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def _find_establishment_for_stored_url(
    db: Session,
    tenant_id: UUID,
    stored: str,
) -> tuple[str, str | None] | None:
    """Resuelve código y nombre del local dueño de una URL almacenada."""
    from sqlalchemy import text

    row = db.execute(
        text(
            """
            SELECT e.code, e.description
            FROM reporte_locales r
            JOIN establishments e
              ON e.id = r.establishment_id AND e.tenant_id = r.tenant_id
            WHERE r.tenant_id = CAST(:tenant_id AS uuid)
              AND (
                EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements_text(COALESCE(r.fotos_urls, '[]'::jsonb)) AS u(val)
                  WHERE u.val = :stored
                )
                OR EXISTS (
                  SELECT 1
                  FROM jsonb_array_elements_text(COALESCE(r.pdfs_urls, '[]'::jsonb)) AS u(val)
                  WHERE u.val = :stored
                )
              )
            LIMIT 1
            """
        ),
        {"tenant_id": str(tenant_id), "stored": stored},
    ).first()
    if row is None:
        return None
    return str(row[0] or ""), row[1]


def _signed_item(stored: str, tenant_id: UUID, *, kind: str, filename: str) -> dict[str, Any]:
    url, expires_at = generate_reporte_local_signed_url(
        stored,
        tenant_id,
        download_filename=filename,
    )
    return {
        "src": stored,
        "kind": kind,
        "filename": filename,
        "download_url": url,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


def get_single_signed_url(
    db: Session,
    tenant_id: UUID,
    *,
    src: str,
) -> dict[str, Any]:
    stored = (src or "").strip()
    if not stored:
        raise ValueError("URL de archivo requerida")
    if read_reporte_local_file_bytes(stored, tenant_id) is None:
        raise ValueError("Archivo no encontrado")

    est_meta = _find_establishment_for_stored_url(db, tenant_id, stored)
    code = est_meta[0] if est_meta else "local"
    description = est_meta[1] if est_meta else None

    kind = "pdf" if stored.lower().endswith(".pdf") or "/pdf/" in stored.lower() else "foto"
    filename = (
        _pdf_download_name(code, description, 0)
        if kind == "pdf"
        else _foto_download_name(code, description, 0)
    )
    return _signed_item(stored, tenant_id, kind=kind, filename=filename)


def resolve_stored_url_download_filename(
    db: Session,
    tenant_id: UUID,
    stored: str,
    *,
    index: int = 0,
) -> str:
    """Nombre de descarga con código y nombre del local."""
    raw = (stored or "").strip()
    est_meta = _find_establishment_for_stored_url(db, tenant_id, raw)
    code = est_meta[0] if est_meta else "local"
    description = est_meta[1] if est_meta else None
    kind = "pdf" if raw.lower().endswith(".pdf") or "/pdf/" in raw.lower() else "foto"
    if kind == "pdf":
        return _pdf_download_name(code, description, index)
    return _foto_download_name(code, description, index)


def get_establishment_signed_urls(
    db: Session,
    tenant_id: UUID,
    establishment_id: int,
    *,
    kind: FileKindFilter = "all",
) -> dict[str, Any]:
    est = db.get(m.InvEstablishment, establishment_id)
    if not est or est.tenant_id != tenant_id:
        raise ValueError("Local no encontrado")

    rep = db.scalar(
        select(m.InvReporteLocal).where(
            m.InvReporteLocal.tenant_id == tenant_id,
            m.InvReporteLocal.establishment_id == establishment_id,
        ),
    )
    fotos = _normalize_url_list(rep.fotos_urls if rep else [])
    pdfs = _normalize_url_list(rep.pdfs_urls if rep else [])
    code = str(est.code or "")
    description = est.description

    items: list[dict[str, Any]] = []
    if kind in ("all", "fotos"):
        for idx, url in enumerate(fotos):
            if read_reporte_local_file_bytes(url, tenant_id) is None:
                continue
            items.append(
                _signed_item(
                    url,
                    tenant_id,
                    kind="foto",
                    filename=_foto_download_name(code, description, idx),
                ),
            )
    if kind in ("all", "pdfs"):
        for idx, url in enumerate(pdfs):
            if read_reporte_local_file_bytes(url, tenant_id) is None:
                continue
            items.append(
                _signed_item(
                    url,
                    tenant_id,
                    kind="pdf",
                    filename=_pdf_download_name(code, description, idx),
                ),
            )

    return {
        "establishment_id": int(est.id),
        "establishment_code": str(est.code or ""),
        "items": items,
    }


def collect_bulk_files(
    db: Session,
    tenant_id: UUID,
    *,
    establishment_ids: list[int] | None,
    department_id: str | None,
    include_fotos: bool,
    include_pdfs: bool,
) -> list[BulkFileItem]:
    ids = [int(x) for x in (establishment_ids or []) if x is not None]
    dept = (department_id or "").strip() or None

    if not ids and not dept:
        raise ValueError("Indique locales específicos o un departamento (ubigeo)")
    if not include_fotos and not include_pdfs:
        raise ValueError("Seleccione al menos fotos o PDF")

    stmt = (
        select(m.InvEstablishment, m.InvReporteLocal)
        .outerjoin(
            m.InvReporteLocal,
            and_(
                m.InvReporteLocal.establishment_id == m.InvEstablishment.id,
                m.InvReporteLocal.tenant_id == tenant_id,
            ),
        )
        .where(m.InvEstablishment.tenant_id == tenant_id)
    )
    if ids:
        stmt = stmt.where(m.InvEstablishment.id.in_(ids))
    if dept:
        stmt = stmt.where(m.InvEstablishment.department_id == dept)
    stmt = stmt.order_by(m.InvEstablishment.code.asc())

    rows = db.execute(stmt).all()
    if not rows:
        raise ValueError("No se encontraron locales con los filtros indicados")

    items: list[BulkFileItem] = []
    for est, rep in rows:
        folder = _safe_folder_name(str(est.code or ""), est.description)
        code = str(est.code or "")
        description = est.description
        fotos = _normalize_url_list(rep.fotos_urls if rep else [])
        pdfs = _normalize_url_list(rep.pdfs_urls if rep else [])

        if include_fotos:
            for idx, url in enumerate(fotos):
                if read_reporte_local_file_bytes(url, tenant_id) is None:
                    continue
                name = _foto_download_name(code, description, idx)
                items.append(
                    BulkFileItem(
                        establishment_id=int(est.id),
                        establishment_code=code,
                        establishment_description=description,
                        kind="foto",
                        stored_url=url,
                        zip_path=f"{folder}/fotos/{name}",
                        download_name=name,
                    ),
                )
        if include_pdfs:
            for idx, url in enumerate(pdfs):
                if read_reporte_local_file_bytes(url, tenant_id) is None:
                    continue
                name = _pdf_download_name(code, description, idx)
                items.append(
                    BulkFileItem(
                        establishment_id=int(est.id),
                        establishment_code=str(est.code or ""),
                        establishment_description=est.description,
                        kind="pdf",
                        stored_url=url,
                        zip_path=f"{folder}/pdfs/{name}",
                        download_name=name,
                    ),
                )

    if not items:
        raise ValueError("Los locales seleccionados no tienen archivos para descargar")
    return items


def schedule_bulk_download(
    db: Session,
    *,
    tenant_id: UUID,
    establishment_ids: list[int] | None,
    department_id: str | None,
    include_fotos: bool,
    include_pdfs: bool,
    created_by_id: UUID | None = None,
) -> dict[str, Any]:
    from app.tasks.reporte_locales_downloads import export_reporte_locales_files_zip_task

    items = collect_bulk_files(
        db,
        tenant_id,
        establishment_ids=establishment_ids,
        department_id=department_id,
        include_fotos=include_fotos,
        include_pdfs=include_pdfs,
    )

    stamp = date.today().isoformat()
    if department_id:
        label = f"dept_{department_id}"
    elif establishment_ids:
        label = f"loc_{len(establishment_ids)}"
    else:
        label = "seleccion"
    filename = f"reporte_locales_{label}_{stamp}.zip"

    job_id = uuid.uuid4()
    row = dl_svc.create_descarga_archivo(
        db,
        job_id=job_id,
        tenant_id=tenant_id,
        module="reporte_locales",
        filename=filename,
        created_by_id=created_by_id,
    )
    db.commit()

    payload = {
        "establishment_ids": establishment_ids or [],
        "department_id": department_id,
        "include_fotos": include_fotos,
        "include_pdfs": include_pdfs,
        "file_count": len(items),
    }
    task = export_reporte_locales_files_zip_task.delay(
        str(job_id),
        str(tenant_id),
        payload,
    )
    dl_svc.set_celery_task_id(db, row, task.id)
    db.commit()

    return {
        "success": True,
        "async_job": True,
        "job_id": str(job_id),
        "message": f"Descarga masiva encolada ({len(items)} archivo(s)). Consulte el estado para obtener el enlace.",
    }
