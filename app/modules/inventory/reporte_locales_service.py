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
from app.modules.inventory.geo_models import InvDepartment, InvDistrict, InvProvince
from app.modules.inventory.schemas import ActaCierrePdfRequest, ReporteLocalWrite
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
        "fecha_inicio_cronograma": rep.fecha_inicio_cronograma if rep else None,
        "fecha_cierre_cronograma": rep.fecha_cierre_cronograma if rep else None,
        "fotos_urls": fotos,
        "pdfs_urls": pdfs,
        "grupo": rep.grupo if rep else None,
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


def list_establishment_situaciones(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Situación de reporte locales por establishment (mapa de locales)."""
    rows = db.execute(
        select(m.InvEstablishment.id, m.InvReporteLocal.situacion)
        .outerjoin(
            m.InvReporteLocal,
            and_(
                m.InvReporteLocal.establishment_id == m.InvEstablishment.id,
                m.InvReporteLocal.tenant_id == tenant_id,
            ),
        )
        .where(m.InvEstablishment.tenant_id == tenant_id)
        .order_by(m.InvEstablishment.code.asc()),
    ).all()
    data = [
        {
            "establishment_id": int(est_id),
            "situacion": (situacion or "pendiente") if situacion in SITUACION_VALUES else "pendiente",
        }
        for est_id, situacion in rows
    ]
    return {"data": data}


def _get_or_create_reporte_row(
    db: Session,
    tenant_id: UUID,
    establishment_id: int,
) -> m.InvReporteLocal:
    row = ensure_reporte_local_row(db, tenant_id, establishment_id)
    return row


def ensure_reporte_local_row(
    db: Session,
    tenant_id: UUID,
    establishment_id: int,
    *,
    commit: bool = False,
) -> m.InvReporteLocal:
    """Crea fila de seguimiento por defecto si el local aún no tiene una."""
    row = db.scalar(
        select(m.InvReporteLocal).where(
            m.InvReporteLocal.tenant_id == tenant_id,
            m.InvReporteLocal.establishment_id == establishment_id,
        ),
    )
    if row is not None:
        return row
    row = m.InvReporteLocal(
        tenant_id=tenant_id,
        establishment_id=establishment_id,
        fotos_urls=[],
        pdfs_urls=[],
        situacion="pendiente",
    )
    db.add(row)
    if commit:
        db.commit()
        db.refresh(row)
    else:
        db.flush()
    return row


def backfill_missing_reporte_locales(db: Session, tenant_id: UUID) -> int:
    """Inserta filas pendientes para locales del tenant sin registro en reporte_locales."""
    from sqlalchemy import text

    result = db.execute(
        text(
            """
            INSERT INTO reporte_locales (
                tenant_id,
                establishment_id,
                situacion,
                fotos_urls,
                pdfs_urls,
                created_at,
                updated_at
            )
            SELECT
                e.tenant_id,
                e.id,
                'pendiente',
                '[]'::jsonb,
                '[]'::jsonb,
                NOW(),
                NOW()
            FROM establishments e
            WHERE e.tenant_id = CAST(:tenant_id AS uuid)
              AND NOT EXISTS (
                SELECT 1
                FROM reporte_locales r
                WHERE r.tenant_id = e.tenant_id
                  AND r.establishment_id = e.id
              )
            """
        ),
        {"tenant_id": str(tenant_id)},
    )
    db.commit()
    return int(result.rowcount or 0)


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
    row.fecha_inicio_cronograma = body.fecha_inicio_cronograma
    row.fecha_cierre_cronograma = body.fecha_cierre_cronograma
    row.fotos_urls = fotos
    row.pdfs_urls = pdfs
    row.grupo = (body.grupo or "").strip()[:50] or None
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


def _geo_description(db: Session, model: type, geo_id: str | None) -> str:
    if not geo_id:
        return ""
    row = db.get(model, geo_id)
    return str(row.description or "").strip() if row else ""


def build_acta_cierre_pdf(
    db: Session,
    tenant_id: UUID,
    establishment_id: int,
    body: ActaCierrePdfRequest,
) -> tuple[bytes, str]:
    """Arma datos del acta desde local, seguimiento y estadísticas; genera PDF."""
    from app.modules.inventory.acta_cierre_pdf import generate_acta_cierre_pdf

    est = db.get(m.InvEstablishment, establishment_id)
    if not est or est.tenant_id != tenant_id:
        raise ValueError("Local no encontrado")

    rep = db.scalar(
        select(m.InvReporteLocal).where(
            m.InvReporteLocal.tenant_id == tenant_id,
            m.InvReporteLocal.establishment_id == establishment_id,
        )
    )

    stats = get_reporte_local_stats(db, tenant_id, establishment_id)
    dept_name = _geo_description(db, InvDepartment, est.department_id)
    prov_name = _geo_description(db, InvProvince, est.province_id)
    dist_name = _geo_description(db, InvDistrict, est.district_id)

    conforme = int(stats.get("margesi_conciliado") or 0)
    sobrantes = int(stats.get("inventario_sobrante") or 0)

    fecha = body.fecha or (rep.fecha_inventario_real if rep and rep.fecha_inventario_real else None)
    grupo = str(rep.grupo or "").strip() if rep else ""

    nota_sistema = str(rep.nota or "").strip() if rep else ""
    obs_adicionales = str(body.observaciones or "").strip()
    if nota_sistema and obs_adicionales:
        observaciones = f"{nota_sistema}\n\n{obs_adicionales}"
    else:
        observaciones = nota_sistema or obs_adicionales or None

    payload: dict[str, Any] = {
        "establishment_code": est.code,
        "establishment_description": est.description,
        "sede_grupo": grupo,
        "fecha": fecha,
        "hora": body.hora,
        "macroregion": grupo,
        "departamento": dept_name,
        "provincia": prov_name,
        "distrito": dist_name,
        "oficina_sede": est.description,
        "representantes_banco": body.representantes_banco,
        "representante_sertec": body.representante_sertec,
        "total_bd": int(stats.get("margesi_total") or 0),
        "conforme": conforme,
        "faltantes": int(stats.get("margesi_faltantes") or 0),
        "sobrantes": sobrantes,
        "total_inventariados": conforme + sobrantes,
        "bn_nombre": body.bn_nombre,
        "bn_cargo": body.bn_cargo,
        "bn_dni": body.bn_dni,
        "sertec_nombre": body.sertec_nombre,
        "sertec_cargo": body.sertec_cargo,
        "sertec_dni": body.sertec_dni,
        "observaciones": observaciones,
    }
    return generate_acta_cierre_pdf(payload)
