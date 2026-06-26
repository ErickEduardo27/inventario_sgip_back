"""Servicio Reporte Locales: seguimiento editable + estadísticas por local."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.reporte_local_storage import (
    MAX_FOTOS,
    MAX_PDFS,
    read_reporte_local_file_bytes,
    upload_reporte_local_foto,
    upload_reporte_local_pdf,
)
from app.modules.inventory import models as m
from app.modules.inventory.schemas import ReporteLocalWrite
from app.modules.inventory.service import paged_meta


SITUACION_VALUES = frozenset({"pendiente", "en_proceso", "terminado"})


def _normalize_url_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return []


def _reporte_local_row_dict(est: m.InvEstablishment, rep: m.InvReporteLocal | None) -> dict[str, Any]:
    fotos = _normalize_url_list(rep.fotos_urls if rep else [])
    pdfs = _normalize_url_list(rep.pdfs_urls if rep else [])
    return {
        "establishment_id": int(est.id),
        "establishment_code": str(est.code or ""),
        "establishment_description": est.description,
        "fecha_inventario_propuesto": rep.fecha_inventario_propuesto if rep else None,
        "fecha_inventario_real": rep.fecha_inventario_real if rep else None,
        "fotos_urls": fotos,
        "pdfs_urls": pdfs,
        "nota": rep.nota if rep else None,
        "situacion": (rep.situacion if rep else "pendiente") or "pendiente",
    }


def list_reporte_locales(
    db: Session,
    tenant_id: UUID,
    *,
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
) -> dict[str, Any]:
    search_term = (search or "").strip()
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
    if search_term:
        pattern = f"%{search_term}%"
        stmt = stmt.where(
            or_(
                m.InvEstablishment.code.ilike(pattern),
                m.InvEstablishment.description.ilike(pattern),
            ),
        )
    stmt = stmt.order_by(m.InvEstablishment.code.asc())

    count_stmt = select(func.count()).select_from(stmt.subquery())
    total = int(db.scalar(count_stmt) or 0)
    offset = (page - 1) * per_page
    rows = db.execute(stmt.offset(offset).limit(per_page)).all()
    data = [_reporte_local_row_dict(est, rep) for est, rep in rows]
    return {"data": data, "meta": paged_meta(total, page, per_page)}


def _get_or_create_reporte_row(
    db: Session,
    tenant_id: UUID,
    establishment_id: int,
) -> m.InvReporteLocal:
    row = db.scalar(
        select(m.InvReporteLocal).where(
            m.InvReporteLocal.tenant_id == tenant_id,
            m.InvReporteLocal.establishment_id == establishment_id,
        ),
    )
    if row is None:
        row = m.InvReporteLocal(
            tenant_id=tenant_id,
            establishment_id=establishment_id,
            fotos_urls=[],
            pdfs_urls=[],
        )
    return row


def upsert_reporte_local(
    db: Session,
    tenant_id: UUID,
    body: ReporteLocalWrite,
) -> dict[str, Any]:
    est = db.get(m.InvEstablishment, body.establishment_id)
    if not est or est.tenant_id != tenant_id:
        raise ValueError("Local no encontrado")

    situacion = (body.situacion or "pendiente").strip()
    if situacion not in SITUACION_VALUES:
        raise ValueError("Situación inválida")

    fotos = _normalize_url_list(body.fotos_urls)
    pdfs = _normalize_url_list(body.pdfs_urls)
    if len(fotos) > MAX_FOTOS:
        raise ValueError(f"Máximo {MAX_FOTOS} fotos por local")
    if len(pdfs) > MAX_PDFS:
        raise ValueError(f"Máximo {MAX_PDFS} documentos PDF por local")

    row = _get_or_create_reporte_row(db, tenant_id, body.establishment_id)
    row.fecha_inventario_propuesto = body.fecha_inventario_propuesto
    row.fecha_inventario_real = body.fecha_inventario_real
    row.fotos_urls = fotos
    row.pdfs_urls = pdfs
    row.nota = (body.nota or "").strip() or None
    row.situacion = situacion
    db.add(row)
    db.commit()
    db.refresh(row)
    return _reporte_local_row_dict(est, row)


def upload_reporte_local_foto_file(
    db: Session,
    tenant_id: UUID,
    establishment_id: int,
    content: bytes,
    *,
    current_count: int = 0,
) -> str:
    est = db.get(m.InvEstablishment, establishment_id)
    if not est or est.tenant_id != tenant_id:
        raise ValueError("Local no encontrado")
    if not content:
        raise ValueError("Archivo vacío")
    if current_count >= MAX_FOTOS:
        raise ValueError(f"Máximo {MAX_FOTOS} fotos por local")

    return upload_reporte_local_foto(
        tenant_id=tenant_id,
        establishment_id=establishment_id,
        content=content,
    )


def upload_reporte_local_pdf_file(
    db: Session,
    tenant_id: UUID,
    establishment_id: int,
    content: bytes,
    filename: str,
    *,
    current_count: int = 0,
) -> str:
    est = db.get(m.InvEstablishment, establishment_id)
    if not est or est.tenant_id != tenant_id:
        raise ValueError("Local no encontrado")
    if not content:
        raise ValueError("Archivo vacío")
    if not (filename or "").lower().endswith(".pdf"):
        raise ValueError("Solo se permiten archivos PDF")
    if current_count >= MAX_PDFS:
        raise ValueError(f"Máximo {MAX_PDFS} documentos PDF por local")

    return upload_reporte_local_pdf(
        tenant_id=tenant_id,
        establishment_id=establishment_id,
        content=content,
        original_name=filename or "documento.pdf",
    )


def read_reporte_local_file_preview(stored: str, tenant_id: UUID) -> tuple[bytes, str]:
    result = read_reporte_local_file_bytes(stored, tenant_id)
    if not result:
        raise ValueError("Archivo no encontrado")
    return result


def get_reporte_local_stats(
    db: Session,
    tenant_id: UUID,
    establishment_id: int,
) -> dict[str, Any]:
    from app.modules.inventory.dashboard_establishment_stats_cache import get_establishment_stats_live

    est = db.get(m.InvEstablishment, establishment_id)
    if not est or est.tenant_id != tenant_id:
        raise ValueError("Local no encontrado")

    return get_establishment_stats_live(db, tenant_id, establishment_id)
