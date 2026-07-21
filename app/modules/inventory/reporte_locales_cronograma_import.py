"""Importación masiva de fechas de cronograma en reporte locales.

Formato (fila 1 = encabezado, se descarta; columnas por índice):
  A (0) código local (establishments.code),
  B (1) fecha inicio cronograma,
  C (2) fecha cierre cronograma.

Por fila: si no existe el local → se omite con advertencia.
Si existe: upsert del seguimiento actualizando solo las fechas de cronograma.
"""

from __future__ import annotations

import io
from datetime import date, datetime
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.inventory import models as m
from app.modules.inventory.reporte_locales_service import ensure_reporte_local_row

_IMPORT_FIELD_NAMES = (
    "establishment_code",
    "fecha_inicio_cronograma",
    "fecha_cierre_cronograma",
)


def _cell_str(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()
    return str(value).strip()


def _parse_date(value: object) -> date | None:
    s = _cell_str(value)
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        parsed = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date()
    except (ValueError, TypeError):
        return None


def _read_raw_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return pd.read_csv(io.StringIO(text), header=None, dtype=str, keep_default_na=False)
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content), header=None, dtype=str, keep_default_na=False)
    raise ValueError("Formato no soportado. Use .xlsx, .xls o .csv")


def parse_cronograma_data_rows(content: bytes, filename: str) -> tuple[pd.DataFrame, int]:
    """Devuelve filas de datos (sin encabezado) y total de filas del archivo (con encabezado)."""
    raw = _read_raw_dataframe(content, filename)
    total_in_file = int(len(raw))
    if raw.empty or len(raw) < 2:
        raise ValueError("El archivo no contiene filas de datos (se requiere encabezado + al menos una fila)")

    data = raw.iloc[1:].copy()
    ncol = min(len(_IMPORT_FIELD_NAMES), data.shape[1])
    if ncol == 0:
        raise ValueError("El archivo no tiene columnas de datos")

    rename = {data.columns[i]: _IMPORT_FIELD_NAMES[i] for i in range(ncol)}
    data = data.rename(columns=rename)
    for field in _IMPORT_FIELD_NAMES:
        if field not in data.columns:
            data[field] = ""
    return data[list(_IMPORT_FIELD_NAMES)], total_in_file


def bulk_import_cronograma(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
) -> dict[str, Any]:
    df, total_in_file = parse_cronograma_data_rows(content, filename)
    errors: list[str] = []
    staging: dict[str, tuple[date | None, date | None]] = {}
    skipped_invalid = 0

    for idx, row in df.iterrows():
        local_code = _cell_str(row.get("establishment_code"))
        if not local_code:
            skipped_invalid += 1
            continue
        fecha_inicio = _parse_date(row.get("fecha_inicio_cronograma"))
        fecha_cierre = _parse_date(row.get("fecha_cierre_cronograma"))
        raw_inicio = _cell_str(row.get("fecha_inicio_cronograma"))
        raw_cierre = _cell_str(row.get("fecha_cierre_cronograma"))
        if raw_inicio and fecha_inicio is None:
            errors.append(f"Fila {int(idx) + 2}: fecha inicio inválida para local {local_code!r}")
            continue
        if raw_cierre and fecha_cierre is None:
            errors.append(f"Fila {int(idx) + 2}: fecha cierre inválida para local {local_code!r}")
            continue
        if fecha_inicio is None and fecha_cierre is None:
            skipped_invalid += 1
            continue
        staging[local_code[:100]] = (fecha_inicio, fecha_cierre)

    if not staging:
        return {
            "success": False,
            "message": "No hay filas válidas para importar",
            "total": total_in_file,
            "registered": 0,
            "inserted": 0,
            "updated": 0,
            "errors": errors
            or [
                "No se encontraron filas con código de local y al menos una fecha de cronograma válida.",
            ],
        }

    codes = list(staging.keys())
    est_rows = db.scalars(
        select(m.InvEstablishment).where(
            m.InvEstablishment.tenant_id == tenant_id,
            m.InvEstablishment.code.in_(codes),
        ),
    ).all()
    est_by_code = {str(e.code): e for e in est_rows if e.code}

    inserted = 0
    updated = 0
    registered = 0
    missing_codes: list[str] = []

    for code, (fecha_inicio, fecha_cierre) in staging.items():
        est = est_by_code.get(code)
        if est is None:
            missing_codes.append(code)
            continue

        existing = db.scalar(
            select(m.InvReporteLocal).where(
                m.InvReporteLocal.tenant_id == tenant_id,
                m.InvReporteLocal.establishment_id == est.id,
            ),
        )
        row = ensure_reporte_local_row(db, tenant_id, int(est.id))
        if fecha_inicio is not None:
            row.fecha_inicio_cronograma = fecha_inicio
        if fecha_cierre is not None:
            row.fecha_cierre_cronograma = fecha_cierre
        db.add(row)
        registered += 1
        if existing is None:
            inserted += 1
        else:
            updated += 1

    if missing_codes:
        preview = ", ".join(missing_codes[:8])
        suffix = f" y {len(missing_codes) - 8} más" if len(missing_codes) > 8 else ""
        errors.append(f"Local(es) no encontrado(s): {preview}{suffix}")

    if registered == 0:
        db.rollback()
        return {
            "success": False,
            "message": "Ningún local del archivo existe en el tenant",
            "total": total_in_file,
            "registered": 0,
            "inserted": 0,
            "updated": 0,
            "errors": errors,
        }

    db.commit()

    message_parts = [f"Importación completada: {registered} local(es) actualizado(s)"]
    if skipped_invalid:
        message_parts.append(f"{skipped_invalid} fila(s) omitida(s)")
    if missing_codes:
        message_parts.append(f"{len(missing_codes)} local(es) no encontrado(s)")

    return {
        "success": True,
        "message": ". ".join(message_parts),
        "total": total_in_file,
        "registered": registered,
        "inserted": inserted,
        "updated": updated,
        "errors": errors[:20],
    }
