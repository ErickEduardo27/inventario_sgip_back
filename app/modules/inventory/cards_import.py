"""Importación masiva de hojas de captura (cabecera ``cards``) desde Excel/CSV.

Fila 1 = encabezado (descartada). Columnas por índice:
  A hoj_num, B hoj_fec, C código ambiente, D código centro de costo,
  E documento usuario responsable (opcional), F email inventariador,
  G email digitador (opcional; si vacío usa el usuario que importa),
  H nota_interna, I nota_ficha.

Upsert por ``hoj_num`` en el tenant. No modifica ``state``, ``hoj_can_tot`` ni ``flag_firma`` en hojas existentes.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy.orm import Session

from app.modules.inventory.bulk_copy import copy_csv_to_temp, csv_cell as _csv_cell

_IMPORT_FIELD_NAMES = (
    "hoj_num",
    "hoj_fec",
    "env_code",
    "cc_code",
    "person_document",
    "inventariador_email",
    "digitador_email",
    "nota_interna",
    "nota_ficha",
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


def _parse_date(value: object) -> str | None:
    s = _cell_str(value)
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    try:
        parsed = pd.to_datetime(s, dayfirst=True, errors="coerce")
        if pd.isna(parsed):
            return None
        return parsed.date().isoformat()
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


def parse_cards_data_rows(content: bytes, filename: str) -> tuple[pd.DataFrame, int]:
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


def bulk_import_cards(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    operator_id: UUID | None = None,
    progress_cb=None,
) -> dict[str, Any]:
    df, total_in_file = parse_cards_data_rows(content, filename)
    warnings: list[str] = []
    staging_by_hoj: dict[str, list[str]] = {}
    valid_row_count = 0
    skipped_invalid = 0

    for _, row in df.iterrows():
        hoj_num = _cell_str(row.get("hoj_num"))
        hoj_fec = _parse_date(row.get("hoj_fec"))
        env_code = _cell_str(row.get("env_code"))
        cc_code = _cell_str(row.get("cc_code"))
        inv_email = _cell_str(row.get("inventariador_email")).lower()
        if not hoj_num or not hoj_fec or not env_code or not cc_code or not inv_email:
            skipped_invalid += 1
            continue
        valid_row_count += 1
        person_doc = _cell_str(row.get("person_document"))
        dig_email = _cell_str(row.get("digitador_email")).lower()
        staging_by_hoj[hoj_num[:50]] = [
            hoj_num[:50],
            hoj_fec,
            env_code[:100],
            cc_code[:100],
            _csv_cell(person_doc),
            inv_email[:200],
            _csv_cell(dig_email),
            _csv_cell(_cell_str(row.get("nota_interna"))),
            _csv_cell(_cell_str(row.get("nota_ficha"))),
        ]

    staging = list(staging_by_hoj.values())
    dup_skipped = valid_row_count - len(staging)
    if dup_skipped > 0:
        warnings.append(
            f"Se omitieron {dup_skipped} fila(s) con N° hoja duplicado "
            f"(se conservó la última ocurrencia de cada número)."
        )
    if skipped_invalid > 0:
        warnings.append(
            f"Se omitieron {skipped_invalid} fila(s) sin N° hoja, fecha, ambiente, "
            f"centro de costo o email de inventariador."
        )

    if not staging:
        return {
            "success": False,
            "message": "No hay filas válidas para importar",
            "total": total_in_file,
            "registered": 0,
            "inserted": 0,
            "updated": 0,
            "errors": warnings or ["Revise columnas obligatorias A–F"],
        }

    tenant_s = str(tenant_id)
    operator_s = str(operator_id) if operator_id else ""
    raw_conn = db.connection().connection
    cur = raw_conn.cursor()
    try:
        copy_csv_to_temp(
            cur,
            table_name="tmp_cards_import",
            table_ddl="""
                CREATE TEMP TABLE tmp_cards_import (
                    hoj_num VARCHAR(50) NOT NULL,
                    hoj_fec DATE NOT NULL,
                    env_code VARCHAR(100) NOT NULL,
                    cc_code VARCHAR(100) NOT NULL,
                    person_document VARCHAR(50),
                    inventariador_email VARCHAR(200) NOT NULL,
                    digitador_email VARCHAR(200),
                    nota_interna TEXT,
                    nota_ficha TEXT
                ) ON COMMIT DROP
            """,
            columns=(
                "hoj_num",
                "hoj_fec",
                "env_code",
                "cc_code",
                "person_document",
                "inventariador_email",
                "digitador_email",
                "nota_interna",
                "nota_ficha",
            ),
            rows=staging,
        )
        if progress_cb:
            progress_cb(25, len(staging), 0, 0)

        cur.execute(
            """
            WITH resolved AS (
                SELECT
                    t.*,
                    env.id AS id_ambiente,
                    cc.id AS id_ccosto,
                    p.id AS id_usuario,
                    inv.id AS id_inventariador,
                    COALESCE(dig.id, NULLIF(%s, '')::uuid, inv.id) AS id_digitador
                FROM tmp_cards_import t
                INNER JOIN enviroments env
                    ON env.tenant_id = %s::uuid
                   AND env.code = t.env_code
                INNER JOIN cost_center cc
                    ON cc.tenant_id = %s::uuid
                   AND cc.code = t.cc_code
                INNER JOIN users inv
                    ON inv.tenant_id = %s::uuid
                   AND lower(inv.email) = t.inventariador_email
                LEFT JOIN users dig
                    ON dig.tenant_id = %s::uuid
                   AND NULLIF(t.digitador_email, '') IS NOT NULL
                   AND lower(dig.email) = t.digitador_email
                LEFT JOIN persons p
                    ON p.tenant_id = %s::uuid
                   AND NULLIF(t.person_document, '') IS NOT NULL
                   AND (
                        p.number = t.person_document
                        OR ltrim(p.number, '0') = ltrim(t.person_document, '0')
                   )
            ),
            upsert AS (
                INSERT INTO cards (
                    tenant_id, hoj_num, hoj_fec, id_ambiente, id_ccosto, id_usuario,
                    id_inventariador, id_digitador, nota_interna, nota_ficha,
                    state, hoj_can_tot, flag_firma
                )
                SELECT
                    %s::uuid,
                    r.hoj_num,
                    r.hoj_fec,
                    r.id_ambiente,
                    r.id_ccosto,
                    r.id_usuario,
                    r.id_inventariador,
                    r.id_digitador,
                    NULLIF(r.nota_interna, ''),
                    NULLIF(r.nota_ficha, ''),
                    1,
                    0,
                    false
                FROM resolved r
                ON CONFLICT (tenant_id, hoj_num) DO UPDATE SET
                    hoj_fec = EXCLUDED.hoj_fec,
                    id_ambiente = EXCLUDED.id_ambiente,
                    id_ccosto = EXCLUDED.id_ccosto,
                    id_usuario = EXCLUDED.id_usuario,
                    id_inventariador = EXCLUDED.id_inventariador,
                    id_digitador = EXCLUDED.id_digitador,
                    nota_interna = EXCLUDED.nota_interna,
                    nota_ficha = EXCLUDED.nota_ficha,
                    updated_at = NOW()
                RETURNING (xmax = 0) AS inserted
            )
            SELECT
                COALESCE(COUNT(*), 0),
                COALESCE(SUM(CASE WHEN inserted THEN 1 ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN NOT inserted THEN 1 ELSE 0 END), 0)
            FROM upsert
            """,
            (
                operator_s,
                tenant_s,
                tenant_s,
                tenant_s,
                tenant_s,
                tenant_s,
                tenant_s,
            ),
        )
        registered, inserted, updated = cur.fetchone() or (0, 0, 0)

        cur.execute(
            """
            SELECT count(*)
            FROM tmp_cards_import t
            LEFT JOIN enviroments env
              ON env.tenant_id = %s::uuid AND env.code = t.env_code
            LEFT JOIN cost_center cc
              ON cc.tenant_id = %s::uuid AND cc.code = t.cc_code
            LEFT JOIN users inv
              ON inv.tenant_id = %s::uuid AND lower(inv.email) = t.inventariador_email
            WHERE env.id IS NULL OR cc.id IS NULL OR inv.id IS NULL
            """,
            (tenant_s, tenant_s, tenant_s),
        )
        unresolved = int(cur.fetchone()[0] or 0)
        if unresolved > 0:
            msg = (
                f"{unresolved} fila(s) no importada(s): ambiente, centro de costo "
                f"o inventariador no encontrado(s)."
            )
            if len(warnings) < MAX_IMPORT_WARNINGS:
                warnings.append(msg)

        if progress_cb:
            progress_cb(90, int(registered), int(updated), int(inserted))

        db.commit()
        if progress_cb:
            progress_cb(100, int(registered), int(updated), int(inserted))

        return {
            "success": True,
            "message": f"Importación completada: {int(registered)} hoja(s) procesada(s)",
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
            "message": "Error al importar hojas de captura",
            "total": total_in_file,
            "registered": 0,
            "inserted": 0,
            "updated": 0,
            "errors": [str(exc)],
        }
    finally:
        cur.close()


def process_cards_upload(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    operator_id: UUID | None = None,
    progress_cb=None,
) -> dict[str, Any]:
    return bulk_import_cards(
        db,
        tenant_id,
        content,
        filename,
        operator_id=operator_id,
        progress_cb=progress_cb,
    )
