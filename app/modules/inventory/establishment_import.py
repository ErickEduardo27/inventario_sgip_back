"""Importación masiva de locales (establishments) vía pandas + PostgreSQL COPY.

Formato Excel/CSV (fila 1 = encabezado, se descarta; datos por índice de columna):
  A (0) code, B (1) description, C (2) address, D (3) country_id,
  E (4) ubigeo (6 dígitos → department_id[:2], province_id[:4], district_id),
  F (5) email, G (6) telephone, H (7) latitude, I (8) longitude.

Upsert por ``code`` dentro del tenant (insert o update; ambos cuentan en inserted/updated).
"""

from __future__ import annotations

import csv
import io
import re
import unicodedata
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

import pandas as pd
from sqlalchemy.orm import Session

from app.modules.inventory import geo_catalog as geo

DEFAULT_COUNTRY_ID = "PE"
from app.modules.inventory.import_common import ASYNC_IMPORT_THRESHOLD
MAX_IMPORT_ERRORS = 200

_IMPORT_FIELD_NAMES = (
    "code",
    "description",
    "address",
    "country_id",
    "ubigeo",
    "email",
    "telephone",
    "latitude",
    "longitude",
)


def _slug_header(value: object) -> str:
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("*", "")
    text = re.sub(r"[\s\-]+", "_", text)
    return text


def _cell_str(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()
    return str(value).strip()


def _ubigeo_digits(raw: str) -> str:
    return re.sub(r"\D", "", raw)


def _cell_coord(value: object, *, kind: str) -> tuple[float | None, str | None]:
    """Devuelve (coordenada, mensaje_error)."""
    s = _cell_str(value)
    if not s:
        return None, None
    normalized = s.replace(",", ".")
    try:
        n = float(normalized)
    except ValueError:
        return None, f"{kind} inválida: «{s}»"
    if kind == "Latitud" and not (-90.0 <= n <= 90.0):
        return None, f"Latitud fuera de rango (-90 a 90): {n}"
    if kind == "Longitud" and not (-180.0 <= n <= 180.0):
        return None, f"Longitud fuera de rango (-180 a 180): {n}"
    return n, None


def _geo_from_ubigeo(ubigeo_raw: str) -> tuple[str | None, str | None, str | None, str | None]:
    """Devuelve (department_id, province_id, district_id, error_message)."""
    digits = _ubigeo_digits(ubigeo_raw)
    if not digits:
        return None, None, None, None
    if len(digits) != 6:
        return None, None, None, f"Ubigeo debe tener 6 dígitos (recibido: «{digits}»)"
    return digits[:2], digits[:4], digits, None


def _read_raw_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return pd.read_csv(io.StringIO(text), header=None, dtype=str, keep_default_na=False)
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content), header=None, dtype=str, keep_default_na=False)
    raise ValueError("Formato no soportado. Use .xlsx, .xls o .csv")


def parse_establishment_upload(content: bytes, filename: str) -> pd.DataFrame:
    raw = _read_raw_dataframe(content, filename)
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
    return data[list(_IMPORT_FIELD_NAMES)]


def validate_establishment_rows(
    db: Session,
    df: pd.DataFrame,
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    valid: list[dict[str, Any]] = []
    seen_codes: set[str] = set()

    for idx, row in df.iterrows():
        row_num = int(idx) + 2  # encabezado + base 1
        code = _cell_str(row.get("code"))
        description = _cell_str(row.get("description"))
        if not code or not description:
            continue

        code_key = code.lower()
        if code_key in seen_codes:
            errors.append(f"Fila {row_num}: código local duplicado «{code}» en el archivo")
            if len(errors) >= MAX_IMPORT_ERRORS:
                break
            continue
        seen_codes.add(code_key)

        ubigeo_raw = _cell_str(row.get("ubigeo"))
        dept_id, prov_id, dist_id, ubigeo_err = _geo_from_ubigeo(ubigeo_raw)
        if ubigeo_err:
            errors.append(f"Fila {row_num}: {ubigeo_err}")
            if len(errors) >= MAX_IMPORT_ERRORS:
                break
            continue

        country_id = (_cell_str(row.get("country_id")) or DEFAULT_COUNTRY_ID)[:2]
        try:
            geo.validate_establishment_geo_ids(db, country_id, dept_id, prov_id, dist_id)
        except ValueError as exc:
            errors.append(f"Fila {row_num}: {exc}")
            if len(errors) >= MAX_IMPORT_ERRORS:
                break
            continue

        latitude, lat_err = _cell_coord(row.get("latitude"), kind="Latitud")
        if lat_err:
            errors.append(f"Fila {row_num}: {lat_err}")
            if len(errors) >= MAX_IMPORT_ERRORS:
                break
            continue
        longitude, lng_err = _cell_coord(row.get("longitude"), kind="Longitud")
        if lng_err:
            errors.append(f"Fila {row_num}: {lng_err}")
            if len(errors) >= MAX_IMPORT_ERRORS:
                break
            continue

        valid.append(
            {
                "row_num": row_num,
                "code": code[:100],
                "description": description[:500],
                "country_id": country_id,
                "department_id": dept_id,
                "province_id": prov_id,
                "district_id": dist_id,
                "address": (_cell_str(row.get("address")) or None),
                "email": (_cell_str(row.get("email")) or None),
                "telephone": (_cell_str(row.get("telephone")) or None),
                "latitude": latitude,
                "longitude": longitude,
            }
        )

    if not valid and not errors:
        errors.append("No hay filas válidas. Revise columnas «Código local» y «Descripción».")
    return valid, errors


def _copy_rows_to_temp(cur, rows: list[dict[str, Any]]) -> None:
    cur.execute(
        """
        CREATE TEMP TABLE tmp_establishments_import (
            row_num INTEGER NOT NULL,
            code VARCHAR(100) NOT NULL,
            description VARCHAR(500) NOT NULL,
            country_id VARCHAR(2),
            department_id VARCHAR(2),
            province_id VARCHAR(4),
            district_id VARCHAR(6),
            address VARCHAR(500),
            email VARCHAR(200),
            telephone VARCHAR(100),
            latitude VARCHAR(50),
            longitude VARCHAR(50)
        ) ON COMMIT DROP
        """
    )
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for row in rows:
        writer.writerow(
            [
                row["row_num"],
                row["code"],
                row["description"],
                row["country_id"] or "",
                row["department_id"] or "",
                row["province_id"] or "",
                row["district_id"] or "",
                row["address"] or "",
                row["email"] or "",
                row["telephone"] or "",
                "" if row["latitude"] is None else str(row["latitude"]),
                "" if row["longitude"] is None else str(row["longitude"]),
            ]
        )
    buf.seek(0)
    cur.copy_expert(
        """
        COPY tmp_establishments_import (
            row_num, code, description, country_id,
            department_id, province_id, district_id, address, email, telephone,
            latitude, longitude
        ) FROM STDIN WITH (FORMAT CSV)
        """,
        buf,
    )


def bulk_import_establishments(
    db: Session,
    tenant_id: UUID,
    rows: list[dict[str, Any]],
    *,
    progress_cb: Callable[[int, int, int, int], None] | None = None,
) -> dict[str, Any]:
    if not rows:
        return {
            "success": False,
            "message": "No hay filas para importar",
            "total_rows": 0,
            "inserted": 0,
            "updated": 0,
            "skipped": 0,
            "errors": ["No hay filas válidas"],
        }

    tenant_s = str(tenant_id)
    raw_conn = db.connection().connection
    cur = raw_conn.cursor()
    try:
        _copy_rows_to_temp(cur, rows)
        if progress_cb:
            progress_cb(20, len(rows), 0, 0)

        cur.execute(
            """
            UPDATE establishments AS e SET
                description = t.description,
                country_id = NULLIF(t.country_id, ''),
                department_id = NULLIF(t.department_id, ''),
                province_id = NULLIF(t.province_id, ''),
                district_id = NULLIF(t.district_id, ''),
                address = NULLIF(t.address, ''),
                email = NULLIF(t.email, ''),
                telephone = NULLIF(t.telephone, ''),
                latitude = CASE
                    WHEN NULLIF(NULLIF(TRIM(t.latitude), ''), 'null') IS NOT NULL
                    THEN NULLIF(NULLIF(TRIM(t.latitude), ''), 'null')::double precision
                    ELSE e.latitude
                END,
                longitude = CASE
                    WHEN NULLIF(NULLIF(TRIM(t.longitude), ''), 'null') IS NOT NULL
                    THEN NULLIF(NULLIF(TRIM(t.longitude), ''), 'null')::double precision
                    ELSE e.longitude
                END,
                updated_at = NOW()
            FROM tmp_establishments_import AS t
            WHERE e.tenant_id = %s
              AND e.code = t.code
            """,
            (tenant_s,),
        )
        updated = cur.rowcount or 0
        if progress_cb:
            progress_cb(60, len(rows), updated, 0)

        cur.execute(
            """
            INSERT INTO establishments (
                tenant_id, code, description, country_id, department_id,
                province_id, district_id, address, email, telephone, latitude, longitude
            )
            SELECT
                %s,
                t.code,
                t.description,
                NULLIF(t.country_id, ''),
                NULLIF(t.department_id, ''),
                NULLIF(t.province_id, ''),
                NULLIF(t.district_id, ''),
                NULLIF(t.address, ''),
                NULLIF(t.email, ''),
                NULLIF(t.telephone, ''),
                NULLIF(NULLIF(TRIM(t.latitude), ''), 'null')::double precision,
                NULLIF(NULLIF(TRIM(t.longitude), ''), 'null')::double precision
            FROM tmp_establishments_import AS t
            WHERE NOT EXISTS (
                SELECT 1 FROM establishments e
                WHERE e.tenant_id = %s AND e.code = t.code
            )
            """,
            (tenant_s, tenant_s),
        )
        inserted = cur.rowcount or 0
        db.commit()
        if progress_cb:
            progress_cb(100, len(rows), updated, inserted)

        registered = inserted + updated
        return {
            "success": True,
            "message": f"Importación completada: {registered} registro(s) procesado(s)",
            "total_rows": len(rows),
            "inserted": inserted,
            "updated": updated,
            "skipped": 0,
            "errors": [],
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {
            "success": False,
            "message": "Error al importar locales",
            "total_rows": len(rows),
            "inserted": 0,
            "updated": 0,
            "skipped": len(rows),
            "errors": [str(exc)],
        }
    finally:
        cur.close()


def process_establishment_upload(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    progress_cb: Callable[[int, int, int, int], None] | None = None,
) -> dict[str, Any]:
    df = parse_establishment_upload(content, filename)
    rows, validation_errors = validate_establishment_rows(db, df)
    if validation_errors and not rows:
        return {
            "success": False,
            "message": "El archivo contiene errores de validación",
            "total_rows": max(0, int(len(df))),
            "inserted": 0,
            "updated": 0,
            "skipped": max(0, int(len(df))),
            "errors": validation_errors,
        }

    result = bulk_import_establishments(db, tenant_id, rows, progress_cb=progress_cb)
    if validation_errors:
        result["errors"] = validation_errors + list(result.get("errors") or [])
        if result.get("success"):
            result["message"] = (
                f"{result['message']}. {len(validation_errors)} fila(s) omitida(s) por validación."
            )
    return result
