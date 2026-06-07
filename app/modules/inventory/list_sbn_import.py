"""Importación masiva de catálogo SBN (list_sbn) desde Excel/CSV.

Fila 1 = encabezado (descartada). Columnas A–N por índice (14 campos).
Upsert por ``code``: create incrementa ``registered``; update no.
Sin validación de código vacío ni duplicados en archivo (comportamiento legacy).
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
    "descripcion",
    "correlativo",
    "clase",
    "es_original",
    "vida_util",
    "porcentaje_depreciacion",
    "clasif_gastos",
    "cuenta_activo",
    "cuenta_orden",
    "valor_aproximado",
    "flag",
    "flag_raa",
    "observaciones",
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


def parse_list_sbn_data_rows(content: bytes, filename: str) -> tuple[pd.DataFrame, int]:
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


def _fields_from_row(row: pd.Series) -> dict[str, Any]:
    """Mapeo plantilla → columnas ``list_sbn`` (valor crudo de celda, sin normalizar cat_cat)."""
    return {
        "code": _cell_str(row.get("code"))[:100],
        "cat_des": _nullable_str(row.get("descripcion")),
        "cat_ulti": _nullable_str(row.get("correlativo")),
        "cat_clase": _nullable_str(row.get("clase")),
        "cat_cat": _nullable_str(row.get("es_original")),
        "cat_cont_vutil": _nullable_str(row.get("vida_util")),
        "cat_cont_pdep": _nullable_str(row.get("porcentaje_depreciacion")),
        "cat_cont_gasto": _nullable_str(row.get("clasif_gastos")),
        "cat_cont_cta_a": _nullable_str(row.get("cuenta_activo")),
        "cat_cont_cta_o": _nullable_str(row.get("cuenta_orden")),
        "cat_cont_valp": _nullable_str(row.get("valor_aproximado")),
        "cat_uso": _nullable_str(row.get("flag")),
        "cat_raa": _nullable_str(row.get("flag_raa")),
        "cat_obs": _nullable_str(row.get("observaciones")),
    }


def _code_index(db: Session, tenant_id: UUID) -> dict[str, m.InvListSbn]:
    index: dict[str, m.InvListSbn] = {}
    rows = db.scalars(select(m.InvListSbn).where(m.InvListSbn.tenant_id == tenant_id)).all()
    for row in rows:
        index[row.code] = row
    return index


def bulk_import_list_sbn(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    progress_cb=None,
) -> dict[str, Any]:
    df, total_in_file = parse_list_sbn_data_rows(content, filename)
    staging: list[list[str]] = []
    for _, row in df.iterrows():
        fields = _fields_from_row(row)
        staging.append(
            [
                _csv_cell(fields["code"]),
                _csv_cell(fields["cat_des"]),
                _csv_cell(fields["cat_ulti"]),
                _csv_cell(fields["cat_clase"]),
                _csv_cell(fields["cat_cat"]),
                _csv_cell(fields["cat_cont_vutil"]),
                _csv_cell(fields["cat_cont_pdep"]),
                _csv_cell(fields["cat_cont_gasto"]),
                _csv_cell(fields["cat_cont_cta_a"]),
                _csv_cell(fields["cat_cont_cta_o"]),
                _csv_cell(fields["cat_cont_valp"]),
                _csv_cell(fields["cat_uso"]),
                _csv_cell(fields["cat_raa"]),
                _csv_cell(fields["cat_obs"]),
            ]
        )

    if not staging:
        return {
            "success": False,
            "message": "No hay filas para importar",
            "total": total_in_file,
            "registered": 0,
            "updated": 0,
            "errors": ["No hay filas válidas"],
        }

    tenant_s = str(tenant_id)
    raw_conn = db.connection().connection
    cur = raw_conn.cursor()
    try:
        copy_csv_to_temp(
            cur,
            table_name="tmp_list_sbn_import",
            table_ddl="""
                CREATE TEMP TABLE tmp_list_sbn_import (
                    code VARCHAR(100) NOT NULL,
                    cat_des VARCHAR(500),
                    cat_ulti VARCHAR(200),
                    cat_clase VARCHAR(200),
                    cat_cat VARCHAR(200),
                    cat_cont_vutil VARCHAR(200),
                    cat_cont_pdep VARCHAR(200),
                    cat_cont_gasto VARCHAR(200),
                    cat_cont_cta_a VARCHAR(200),
                    cat_cont_cta_o VARCHAR(200),
                    cat_cont_valp VARCHAR(200),
                    cat_uso VARCHAR(200),
                    cat_raa VARCHAR(200),
                    cat_obs TEXT
                ) ON COMMIT DROP
            """,
            columns=(
                "code", "cat_des", "cat_ulti", "cat_clase", "cat_cat",
                "cat_cont_vutil", "cat_cont_pdep", "cat_cont_gasto",
                "cat_cont_cta_a", "cat_cont_cta_o", "cat_cont_valp",
                "cat_uso", "cat_raa", "cat_obs",
            ),
            rows=staging,
        )
        if progress_cb:
            progress_cb(40, len(staging), 0, 0)

        cur.execute(
            """
            WITH upsert AS (
                INSERT INTO list_sbn (
                    tenant_id, code, cat_des, cat_ulti, cat_clase, cat_cat,
                    cat_cont_vutil, cat_cont_pdep, cat_cont_gasto,
                    cat_cont_cta_a, cat_cont_cta_o, cat_cont_valp,
                    cat_uso, cat_raa, cat_obs
                )
                SELECT
                    %s::uuid,
                    t.code,
                    NULLIF(t.cat_des, ''),
                    NULLIF(t.cat_ulti, ''),
                    NULLIF(t.cat_clase, ''),
                    NULLIF(t.cat_cat, ''),
                    NULLIF(t.cat_cont_vutil, ''),
                    NULLIF(t.cat_cont_pdep, ''),
                    NULLIF(t.cat_cont_gasto, ''),
                    NULLIF(t.cat_cont_cta_a, ''),
                    NULLIF(t.cat_cont_cta_o, ''),
                    NULLIF(t.cat_cont_valp, ''),
                    NULLIF(t.cat_uso, ''),
                    NULLIF(t.cat_raa, ''),
                    NULLIF(t.cat_obs, '')
                FROM tmp_list_sbn_import t
                ON CONFLICT (tenant_id, code) DO UPDATE SET
                    cat_des = EXCLUDED.cat_des,
                    cat_ulti = EXCLUDED.cat_ulti,
                    cat_clase = EXCLUDED.cat_clase,
                    cat_cat = EXCLUDED.cat_cat,
                    cat_cont_vutil = EXCLUDED.cat_cont_vutil,
                    cat_cont_pdep = EXCLUDED.cat_cont_pdep,
                    cat_cont_gasto = EXCLUDED.cat_cont_gasto,
                    cat_cont_cta_a = EXCLUDED.cat_cont_cta_a,
                    cat_cont_cta_o = EXCLUDED.cat_cont_cta_o,
                    cat_cont_valp = EXCLUDED.cat_cont_valp,
                    cat_uso = EXCLUDED.cat_uso,
                    cat_raa = EXCLUDED.cat_raa,
                    cat_obs = EXCLUDED.cat_obs,
                    updated_at = NOW()
                RETURNING (xmax = 0) AS inserted
            )
            SELECT
                COALESCE(SUM(CASE WHEN inserted THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN NOT inserted THEN 1 ELSE 0 END), 0)
            FROM upsert
            """,
            (tenant_s,),
        )
        registered, updated = cur.fetchone() or (0, 0)
        db.commit()
        if progress_cb:
            progress_cb(100, len(staging), int(updated), int(registered))

        return {
            "success": True,
            "message": f"Importación completada: {int(registered)} nuevo(s), {int(updated)} actualizado(s)",
            "total": total_in_file,
            "registered": int(registered),
            "updated": int(updated),
            "inserted": int(registered),
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {
            "success": False,
            "message": "Error al importar catálogo SBN",
            "total": total_in_file,
            "registered": 0,
            "updated": 0,
            "errors": [str(exc)],
        }
    finally:
        cur.close()


def process_list_sbn_upload(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    progress_cb=None,
) -> dict[str, Any]:
    return bulk_import_list_sbn(
        db, tenant_id, content, filename, progress_cb=progress_cb
    )
