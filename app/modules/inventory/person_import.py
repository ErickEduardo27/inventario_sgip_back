"""Importación masiva de personas desde Excel/CSV.

Fila 1 = encabezado. Columnas A–Q por índice (ver spec CentroCosto / Personas import).
Upsert por ``extra.codigo_interno`` (columna A). ``type`` viene del query param (ej. customers).
Ubicación fija: PE / 01 / 0101 / 010101. Género, celular, anexo y condición se leen pero no persisten.
"""

from __future__ import annotations

import io
import re
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

import json

from app.modules.inventory import models as m
from app.modules.inventory.bulk_copy import copy_csv_to_temp, csv_cell as _csv_cell

_IMPORT_FIELD_NAMES = (
    "internal_code",
    "identity_document_type_id",
    "number",
    "last_name",
    "m_last_name",
    "first_names",
    "gender",
    "mobile",
    "telephone",
    "anex",
    "email",
    "condition",
    "job",
    "enviroment_code",
    "boss_code",
    "cc_code",
    "observation",
)

FIXED_COUNTRY_ID = "PE"
FIXED_DEPARTMENT_ID = "01"
FIXED_PROVINCE_ID = "0101"
FIXED_DISTRICT_ID = "010101"

# Catálogo Laravel → valor almacenado (string)
_DOC_TYPE_BY_ID: dict[str, str] = {
    "0": "0",
    "1": "DNI",
    "4": "CE",
    "6": "RUC",
    "7": "PAS",
    "dni": "DNI",
    "ce": "CE",
    "ruc": "RUC",
    "pas": "PAS",
    "pasaporte": "PAS",
}


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


def _normalize_doc_type(raw: object) -> str | None:
    s = _cell_str(raw)
    if not s:
        return None
    if re.fullmatch(r"\d+", s):
        return _DOC_TYPE_BY_ID.get(s, s)
    key = s.lower().replace(" ", "")
    return _DOC_TYPE_BY_ID.get(key, s.upper() if len(s) <= 4 else s)


def _read_raw_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return pd.read_csv(io.StringIO(text), header=None, dtype=str, keep_default_na=False)
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content), header=None, dtype=str, keep_default_na=False)
    raise ValueError("Formato no soportado. Use .xlsx, .xls o .csv")


def parse_person_data_rows(content: bytes, filename: str) -> tuple[pd.DataFrame, int]:
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


def _internal_code_index(db: Session, tenant_id: UUID) -> dict[str, m.InvPerson]:
    index: dict[str, m.InvPerson] = {}
    rows = db.scalars(select(m.InvPerson).where(m.InvPerson.tenant_id == tenant_id)).all()
    for row in rows:
        ex = row.extra if isinstance(row.extra, dict) else {}
        code = str(ex.get("codigo_interno") or "").strip()
        if code:
            index[code] = row
    return index


def _build_person_fields(row: pd.Series, person_type: str) -> dict[str, Any] | None:
    internal_code = _cell_str(row.get("internal_code"))
    if not internal_code:
        return None

    first_names = _cell_str(row.get("first_names"))
    last_name = _cell_str(row.get("last_name"))
    m_last_name = _cell_str(row.get("m_last_name"))
    full_name = " ".join(x for x in (last_name, m_last_name, first_names) if x).strip()

    extra: dict[str, Any] = {
        "codigo_interno": internal_code[:100],
        "apellido_paterno": last_name or None,
        "apellido_materno": m_last_name or None,
        "nombre": first_names or None,
        "job": _nullable_str(row.get("job")),
        "boss_code": _nullable_str(row.get("boss_code")),
    }

    return {
        "type": person_type,
        "identity_document_type_id": _normalize_doc_type(row.get("identity_document_type_id")),
        "number": _nullable_str(row.get("number")),
        "name": full_name or first_names or None,
        "trade_name": first_names or full_name or None,
        "country_id": FIXED_COUNTRY_ID,
        "department_id": FIXED_DEPARTMENT_ID,
        "province_id": FIXED_PROVINCE_ID,
        "district_id": FIXED_DISTRICT_ID,
        "email": _nullable_str(row.get("email")),
        "telephone": _nullable_str(row.get("telephone")),
        "enviroment_code": _nullable_str(row.get("enviroment_code")),
        "cc_code": _nullable_str(row.get("cc_code")),
        "observation": _nullable_str(row.get("observation")),
        "enabled": True,
        "extra": extra,
    }


def bulk_import_persons(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    person_type: str = "customers",
    progress_cb=None,
) -> dict[str, Any]:
    df, total_in_file = parse_person_data_rows(content, filename)
    ptype = (person_type or "customers").strip() or "customers"
    staging: list[list[str]] = []
    for _, row in df.iterrows():
        fields = _build_person_fields(row, ptype)
        if not fields:
            continue
        extra = fields.pop("extra") or {}
        staging.append(
            [
                _csv_cell(extra.get("codigo_interno")),
                _csv_cell(fields.get("type")),
                _csv_cell(fields.get("identity_document_type_id")),
                _csv_cell(fields.get("number")),
                _csv_cell(fields.get("name")),
                _csv_cell(fields.get("trade_name")),
                _csv_cell(fields.get("country_id")),
                _csv_cell(fields.get("department_id")),
                _csv_cell(fields.get("province_id")),
                _csv_cell(fields.get("district_id")),
                _csv_cell(fields.get("email")),
                _csv_cell(fields.get("telephone")),
                _csv_cell(fields.get("enviroment_code")),
                _csv_cell(fields.get("cc_code")),
                _csv_cell(fields.get("observation")),
                json.dumps(extra, ensure_ascii=False),
            ]
        )

    if not staging:
        return {
            "success": False,
            "message": "No hay filas válidas para importar",
            "total": total_in_file,
            "registered": 0,
            "inserted": 0,
            "updated": 0,
            "errors": ["Revise la columna código interno (A)"],
        }

    tenant_s = str(tenant_id)
    raw_conn = db.connection().connection
    cur = raw_conn.cursor()
    try:
        copy_csv_to_temp(
            cur,
            table_name="tmp_person_import",
            table_ddl="""
                CREATE TEMP TABLE tmp_person_import (
                    internal_code VARCHAR(100) NOT NULL,
                    type VARCHAR(50),
                    identity_document_type_id VARCHAR(50),
                    number VARCHAR(50),
                    name VARCHAR(500),
                    trade_name VARCHAR(500),
                    country_id VARCHAR(50),
                    department_id VARCHAR(50),
                    province_id VARCHAR(50),
                    district_id VARCHAR(50),
                    email VARCHAR(200),
                    telephone VARCHAR(100),
                    enviroment_code VARCHAR(100),
                    cc_code VARCHAR(100),
                    observation TEXT,
                    extra_json TEXT
                ) ON COMMIT DROP
            """,
            columns=(
                "internal_code", "type", "identity_document_type_id", "number",
                "name", "trade_name", "country_id", "department_id", "province_id",
                "district_id", "email", "telephone", "enviroment_code", "cc_code",
                "observation", "extra_json",
            ),
            rows=staging,
        )
        if progress_cb:
            progress_cb(35, len(staging), 0, 0)

        cur.execute(
            """
            UPDATE persons AS p SET
                type = NULLIF(t.type, ''),
                identity_document_type_id = NULLIF(t.identity_document_type_id, ''),
                number = NULLIF(t.number, ''),
                name = NULLIF(t.name, ''),
                trade_name = NULLIF(t.trade_name, ''),
                country_id = NULLIF(t.country_id, ''),
                department_id = NULLIF(t.department_id, ''),
                province_id = NULLIF(t.province_id, ''),
                district_id = NULLIF(t.district_id, ''),
                email = NULLIF(t.email, ''),
                telephone = NULLIF(t.telephone, ''),
                enviroment_code = NULLIF(t.enviroment_code, ''),
                cc_code = NULLIF(t.cc_code, ''),
                observation = NULLIF(t.observation, ''),
                extra = t.extra_json::jsonb,
                updated_at = NOW()
            FROM tmp_person_import AS t
            WHERE p.tenant_id = %s::uuid
              AND p.extra->>'codigo_interno' = t.internal_code
            """,
            (tenant_s,),
        )
        updated = int(cur.rowcount or 0)
        if progress_cb:
            progress_cb(65, len(staging), updated, 0)

        cur.execute(
            """
            INSERT INTO persons (
                tenant_id, type, identity_document_type_id, number, name, trade_name,
                country_id, department_id, province_id, district_id,
                email, telephone, enviroment_code, cc_code, observation,
                enabled, extra
            )
            SELECT
                %s::uuid,
                NULLIF(t.type, ''),
                NULLIF(t.identity_document_type_id, ''),
                NULLIF(t.number, ''),
                NULLIF(t.name, ''),
                NULLIF(t.trade_name, ''),
                NULLIF(t.country_id, ''),
                NULLIF(t.department_id, ''),
                NULLIF(t.province_id, ''),
                NULLIF(t.district_id, ''),
                NULLIF(t.email, ''),
                NULLIF(t.telephone, ''),
                NULLIF(t.enviroment_code, ''),
                NULLIF(t.cc_code, ''),
                NULLIF(t.observation, ''),
                TRUE,
                t.extra_json::jsonb
            FROM tmp_person_import t
            WHERE NOT EXISTS (
                SELECT 1 FROM persons p
                WHERE p.tenant_id = %s::uuid
                  AND p.extra->>'codigo_interno' = t.internal_code
            )
            """,
            (tenant_s, tenant_s),
        )
        inserted = int(cur.rowcount or 0)
        registered = inserted + updated
        db.commit()
        if progress_cb:
            progress_cb(100, int(registered), int(updated), int(inserted))

        return {
            "success": True,
            "message": f"Importación completada: {int(registered)} persona(s) procesada(s)",
            "total": total_in_file,
            "registered": int(registered),
            "inserted": int(inserted),
            "updated": int(updated),
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {
            "success": False,
            "message": "Error al importar personas",
            "total": total_in_file,
            "registered": 0,
            "inserted": 0,
            "updated": 0,
            "errors": [str(exc)],
        }
    finally:
        cur.close()


def process_person_upload(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    person_type: str = "customers",
    progress_cb=None,
) -> dict[str, Any]:
    return bulk_import_persons(
        db,
        tenant_id,
        content,
        filename,
        person_type=person_type,
        progress_cb=progress_cb,
    )
