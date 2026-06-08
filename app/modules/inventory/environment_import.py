"""Importación masiva de ambientes (enviroments) desde Excel/CSV.

Formato (fila 1 = encabezado, se descarta; columnas por índice):
  A (0) code, B (1) description, C (2) código local (establishments.code),
  D (3) floor, E (4) observation, F (5) telephone, G (6) anex.

Por fila: si no existe el local (columna C) → se omite sin error.
Si existe el local: upsert del ambiente por ``code`` (global en el tenant).
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
    "establishment_code",
    "floor",
    "observation",
    "telephone",
    "anex",
)


def _cell_str(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()
    return str(value).strip()


def _nullable_str(value: object) -> str | None:
    s = _cell_str(value)
    return s if s else None


def _read_raw_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return pd.read_csv(io.StringIO(text), header=None, dtype=str, keep_default_na=False)
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content), header=None, dtype=str, keep_default_na=False)
    raise ValueError("Formato no soportado. Use .xlsx, .xls o .csv")


def parse_environment_data_rows(content: bytes, filename: str) -> tuple[pd.DataFrame, int]:
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


def bulk_import_environments(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    progress_cb=None,
) -> dict[str, Any]:
    df, total_in_file = parse_environment_data_rows(content, filename)
    warnings: list[str] = []
    staging_by_code: dict[str, list[str]] = {}
    valid_row_count = 0
    for _, row in df.iterrows():
        code = _cell_str(row.get("code"))
        if not code:
            continue
        local_code = _cell_str(row.get("establishment_code"))
        if not local_code:
            continue
        valid_row_count += 1
        staging_by_code[code[:100]] = [
            code[:100],
            _csv_cell(_nullable_str(row.get("description"))),
            local_code[:100],
            _csv_cell(_nullable_str(row.get("floor"))),
            _csv_cell(_nullable_str(row.get("observation"))),
            _csv_cell(_nullable_str(row.get("telephone"))),
            _csv_cell(_nullable_str(row.get("anex"))),
        ]

    staging = list(staging_by_code.values())
    dup_skipped = valid_row_count - len(staging)
    if dup_skipped > 0:
        warnings.append(
            f"Se omitieron {dup_skipped} fila(s) con código de ambiente duplicado "
            f"(se conservó la última ocurrencia de cada código)."
        )

    if not staging:
        return {
            "success": False,
            "message": "No hay filas válidas para importar",
            "total": total_in_file,
            "registered": 0,
            "inserted": 0,
            "updated": 0,
            "errors": ["Revise código de ambiente y código de local"],
        }

    tenant_s = str(tenant_id)
    raw_conn = db.connection().connection
    cur = raw_conn.cursor()
    try:
        copy_csv_to_temp(
            cur,
            table_name="tmp_env_import",
            table_ddl="""
                CREATE TEMP TABLE tmp_env_import (
                    code VARCHAR(100) NOT NULL,
                    description VARCHAR(500),
                    establishment_code VARCHAR(100) NOT NULL,
                    floor VARCHAR(100),
                    observation TEXT,
                    telephone VARCHAR(100),
                    anex VARCHAR(100)
                ) ON COMMIT DROP
            """,
            columns=(
                "code", "description", "establishment_code",
                "floor", "observation", "telephone", "anex",
            ),
            rows=staging,
        )
        if progress_cb:
            progress_cb(30, len(staging), 0, 0)

        cur.execute(
            """
            WITH resolved AS (
                SELECT
                    t.*,
                    e.id AS establishment_id
                FROM tmp_env_import t
                INNER JOIN establishments e
                    ON e.tenant_id = %s::uuid
                   AND e.code = t.establishment_code
            ),
            upsert AS (
                INSERT INTO enviroments (
                    tenant_id, code, description, establishment_id,
                    floor, observation, telephone, anex
                )
                SELECT
                    %s::uuid,
                    r.code,
                    NULLIF(r.description, ''),
                    r.establishment_id,
                    NULLIF(r.floor, ''),
                    NULLIF(r.observation, ''),
                    NULLIF(r.telephone, ''),
                    NULLIF(r.anex, '')
                FROM resolved r
                ON CONFLICT (tenant_id, code) DO UPDATE SET
                    description = EXCLUDED.description,
                    establishment_id = EXCLUDED.establishment_id,
                    floor = EXCLUDED.floor,
                    observation = EXCLUDED.observation,
                    telephone = EXCLUDED.telephone,
                    anex = EXCLUDED.anex,
                    updated_at = NOW()
                RETURNING (xmax = 0) AS inserted
            )
            SELECT
                COALESCE(COUNT(*), 0),
                COALESCE(SUM(CASE WHEN inserted THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN NOT inserted THEN 1 ELSE 0 END), 0)
            FROM upsert
            """,
            (tenant_s, tenant_s),
        )
        registered, inserted, updated = cur.fetchone() or (0, 0, 0)
        db.commit()
        if progress_cb:
            progress_cb(100, int(registered), int(updated), int(inserted))

        return {
            "success": True,
            "message": f"Importación completada: {int(registered)} ambiente(s) procesado(s)",
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
            "message": "Error al importar ambientes",
            "total": total_in_file,
            "registered": 0,
            "inserted": 0,
            "updated": 0,
            "errors": [str(exc)],
        }
    finally:
        cur.close()


def process_environment_upload(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    progress_cb=None,
) -> dict[str, Any]:
    return bulk_import_environments(
        db, tenant_id, content, filename, progress_cb=progress_cb
    )
