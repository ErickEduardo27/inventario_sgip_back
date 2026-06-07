"""Importación masiva de centros de costo desde Excel/CSV.

Fila 1 = encabezado (descartada). Columnas por índice:
  A code, B description, C documento encargado (persons.number; vacío o '0' = sin encargado),
  D código CC principal (cost_center.code; vacío = sin padre → principal_center_id NULL).

Upsert por ``code`` en el tenant. Si el CC principal no existe se registra igual (sin padre) y se avisa.
"""

from __future__ import annotations

import io
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.inventory import models as m
from app.modules.inventory.bulk_copy import copy_csv_to_temp, csv_cell as _csv_cell

_IMPORT_FIELD_NAMES = (
    "code",
    "description",
    "encargado_document",
    "principal_cc_code",
)

MAX_IMPORT_WARNINGS = 30


def _cell_str(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()
    return str(value).strip()


def _encargado_optional(document: str) -> bool:
    return not document or document == "0"


def _read_raw_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return pd.read_csv(io.StringIO(text), header=None, dtype=str, keep_default_na=False)
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content), header=None, dtype=str, keep_default_na=False)
    raise ValueError("Formato no soportado. Use .xlsx, .xls o .csv")


def parse_cost_center_data_rows(content: bytes, filename: str) -> tuple[pd.DataFrame, int]:
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


def _lookup_person(document: str, person_by_number: dict[str, int]) -> int | None:
    if _encargado_optional(document):
        return None
    if document in person_by_number:
        return person_by_number[document]
    stripped = document.lstrip("0")
    if stripped and stripped in person_by_number:
        return person_by_number[stripped]
    return None


def _upsert_cost_center(
    db: Session,
    tenant_id: UUID,
    *,
    code: str,
    description: str,
    personal_id: int | None,
    principal_center_id: int | None,
) -> tuple[bool, int]:
    """Devuelve (es_nuevo, id)."""
    payload = {
        "code": code[:100],
        "description": description[:70],
        "personal_id": personal_id,
        "principal_center_id": principal_center_id,
    }
    existing = db.scalar(
        select(m.InvCostCenter).where(
            m.InvCostCenter.tenant_id == tenant_id,
            m.InvCostCenter.code == code,
        )
    )
    if existing:
        for key, val in payload.items():
            setattr(existing, key, val)
        db.add(existing)
        db.flush()
        return False, int(existing.id)
    row = m.InvCostCenter(tenant_id=tenant_id, **payload)
    db.add(row)
    db.flush()
    return True, int(row.id)


def bulk_import_cost_centers(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    progress_cb=None,
) -> dict[str, Any]:
    df, total_in_file = parse_cost_center_data_rows(content, filename)
    staging: list[list[str]] = []
    warnings: list[str] = []
    for idx, row in df.iterrows():
        code = _cell_str(row.get("code"))
        description = _cell_str(row.get("description"))
        if not code or not description:
            continue
        encargado = _cell_str(row.get("encargado_document"))
        principal = _cell_str(row.get("principal_cc_code"))
        staging.append([code[:100], description[:70], _csv_cell(encargado), _csv_cell(principal)])

    if not staging:
        return {
            "success": False,
            "message": "No hay filas válidas para importar",
            "total": total_in_file,
            "registered": 0,
            "inserted": 0,
            "updated": 0,
            "errors": ["Revise código y descripción"],
        }

    tenant_s = str(tenant_id)
    raw_conn = db.connection().connection
    cur = raw_conn.cursor()
    try:
        copy_csv_to_temp(
            cur,
            table_name="tmp_cc_import",
            table_ddl="""
                CREATE TEMP TABLE tmp_cc_import (
                    code VARCHAR(100) NOT NULL,
                    description VARCHAR(70) NOT NULL,
                    encargado_document VARCHAR(50),
                    principal_cc_code VARCHAR(100)
                ) ON COMMIT DROP
            """,
            columns=("code", "description", "encargado_document", "principal_cc_code"),
            rows=staging,
        )
        if progress_cb:
            progress_cb(25, len(staging), 0, 0)

        cur.execute(
            """
            WITH resolved AS (
                SELECT
                    t.*,
                    p.id AS personal_id,
                    pc.id AS principal_center_id
                FROM tmp_cc_import t
                LEFT JOIN persons p
                    ON p.tenant_id = %s::uuid
                   AND (
                        (NULLIF(t.encargado_document, '') IS NOT NULL AND p.number = t.encargado_document)
                        OR (NULLIF(t.encargado_document, '') IS NOT NULL
                            AND ltrim(p.number, '0') = ltrim(t.encargado_document, '0'))
                   )
                LEFT JOIN cost_center pc
                    ON pc.tenant_id = %s::uuid
                   AND pc.code = NULLIF(t.principal_cc_code, '')
            ),
            upsert AS (
                INSERT INTO cost_center (
                    tenant_id, code, description, personal_id, principal_center_id
                )
                SELECT
                    %s::uuid,
                    r.code,
                    r.description,
                    r.personal_id,
                    CASE WHEN NULLIF(r.principal_cc_code, '') IS NULL THEN NULL ELSE r.principal_center_id END
                FROM resolved r
                ON CONFLICT (tenant_id, code) DO UPDATE SET
                    description = EXCLUDED.description,
                    personal_id = EXCLUDED.personal_id,
                    principal_center_id = EXCLUDED.principal_center_id,
                    updated_at = NOW()
                RETURNING (xmax = 0) AS inserted
            )
            SELECT
                COALESCE(COUNT(*), 0),
                COALESCE(SUM(CASE WHEN inserted THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN NOT inserted THEN 1 ELSE 0 END), 0)
            FROM upsert
            """,
            (tenant_s, tenant_s, tenant_s),
        )
        registered, inserted, updated = cur.fetchone() or (0, 0, 0)

        cur.execute(
            """
            UPDATE cost_center AS cc SET
                principal_center_id = parent.id,
                updated_at = NOW()
            FROM tmp_cc_import t
            JOIN cost_center parent
              ON parent.tenant_id = %s::uuid
             AND parent.code = t.principal_cc_code
            WHERE cc.tenant_id = %s::uuid
              AND cc.code = t.code
              AND NULLIF(t.principal_cc_code, '') IS NOT NULL
              AND cc.principal_center_id IS DISTINCT FROM parent.id
            """,
            (tenant_s, tenant_s),
        )

        if progress_cb:
            progress_cb(90, int(registered), int(updated), int(inserted))

        db.commit()
        if progress_cb:
            progress_cb(100, int(registered), int(updated), int(inserted))

        return {
            "success": True,
            "message": f"Importación completada: {int(registered)} centro(s) de costo procesado(s)",
            "total": total_in_file,
            "registered": int(registered),
            "inserted": int(inserted),
            "updated": int(updated),
            "errors": warnings,
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {
            "success": False,
            "message": "Error al importar centros de costo",
            "total": total_in_file,
            "registered": 0,
            "inserted": 0,
            "updated": 0,
            "errors": [str(exc)],
        }
    finally:
        cur.close()


def process_cost_center_upload(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    progress_cb=None,
) -> dict[str, Any]:
    return bulk_import_cost_centers(
        db, tenant_id, content, filename, progress_cb=progress_cb
    )
