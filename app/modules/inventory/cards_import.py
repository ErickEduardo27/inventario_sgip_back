"""Importación masiva de hojas de captura (cabecera ``cards``) desde Excel/CSV.

Fila 1 = encabezado (descartada). Columnas por índice (A–I):
  A Número de hoja, B hoj_fec, C code_ambiente, D code_ccosto,
  E number_usuario (opcional; vacío o 0 = sin responsable),
  F number_digitador, G number_inventariador,
  H nota_interna (opcional), I nota_ficha (opcional).

Los números de digitador/inventariador se resuelven vía ``persons.number`` → ``users.email``.
Si el digitador no se encuentra, se usa el usuario que ejecuta la importación.

Upsert por ``hoj_num`` en el tenant. No modifica ``state``, ``hoj_can_tot`` ni ``flag_firma``.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy.orm import Session

from app.core.inventory_numbers import parse_inventory_number
from app.modules.inventory.bulk_copy import copy_csv_to_temp, csv_cell as _csv_cell

_IMPORT_FIELD_NAMES = (
    "hoj_num",
    "hoj_fec",
    "env_code",
    "cc_code",
    "person_document",
    "digitador_number",
    "inventariador_number",
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


def _optional_person_document(value: object) -> str:
    s = _cell_str(value)
    if not s or s == "0":
        return ""
    return s


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
        inv_number = _cell_str(row.get("inventariador_number"))
        if not hoj_num or not hoj_fec or not env_code or not cc_code or not inv_number:
            skipped_invalid += 1
            continue
        try:
            hoj_key = str(parse_inventory_number(hoj_num, field="Número de hoja"))
        except ValueError:
            skipped_invalid += 1
            continue
        valid_row_count += 1
        person_doc = _optional_person_document(row.get("person_document"))
        dig_number = _cell_str(row.get("digitador_number"))
        staging_by_hoj[hoj_key] = [
            hoj_key,
            hoj_fec,
            env_code[:100],
            cc_code[:100],
            _csv_cell(person_doc),
            _csv_cell(dig_number),
            inv_number[:50],
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
            f"centro de costo o número de inventariador."
        )

    if not staging:
        return {
            "success": False,
            "message": "No hay filas válidas para importar",
            "total": total_in_file,
            "registered": 0,
            "inserted": 0,
            "updated": 0,
            "errors": warnings or ["Revise columnas obligatorias A–D y G"],
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
                    digitador_number VARCHAR(50),
                    inventariador_number VARCHAR(50) NOT NULL,
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
                "digitador_number",
                "inventariador_number",
                "nota_interna",
                "nota_ficha",
            ),
            rows=staging,
        )
        if progress_cb:
            progress_cb(25, len(staging), 0, 0)

        cur.execute(
            """
            CREATE TEMP TABLE tmp_cards_est_before ON COMMIT DROP AS
            SELECT c.id AS card_id, env.establishment_id
            FROM cards c
            INNER JOIN tmp_cards_import t
                ON c.tenant_id = %s::uuid
               AND c.hoj_num = NULLIF(regexp_replace(trim(t.hoj_num), '[^0-9]', '', 'g'), '')::bigint
            INNER JOIN enviroments env
                ON env.id = c.id_ambiente
               AND env.tenant_id = c.tenant_id
            WHERE env.establishment_id IS NOT NULL
            """,
            (tenant_s,),
        )

        cur.execute(
            """
            WITH resolved AS (
                SELECT
                    t.*,
                    env.id AS id_ambiente,
                    cc.id AS id_ccosto,
                    p.id AS id_usuario,
                    inv_u.id AS id_inventariador,
                    COALESCE(dig_u.id, NULLIF(%s, '')::uuid, inv_u.id) AS id_digitador
                FROM tmp_cards_import t
                INNER JOIN enviroments env
                    ON env.tenant_id = %s::uuid
                   AND env.code = t.env_code
                INNER JOIN cost_center cc
                    ON cc.tenant_id = %s::uuid
                   AND cc.code = t.cc_code
                INNER JOIN persons p_inv
                    ON p_inv.tenant_id = %s::uuid
                   AND (
                        p_inv.number = t.inventariador_number
                        OR ltrim(p_inv.number, '0') = ltrim(t.inventariador_number, '0')
                   )
                INNER JOIN users inv_u
                    ON inv_u.tenant_id = %s::uuid
                   AND inv_u.is_deleted = false
                   AND (
                        (
                            NULLIF(p_inv.email, '') IS NOT NULL
                            AND lower(inv_u.email) = lower(p_inv.email)
                        )
                        OR inv_u.full_name = p_inv.name
                   )
                LEFT JOIN persons p
                    ON p.tenant_id = %s::uuid
                   AND NULLIF(t.person_document, '') IS NOT NULL
                   AND (
                        p.number = t.person_document
                        OR ltrim(p.number, '0') = ltrim(t.person_document, '0')
                   )
                LEFT JOIN persons p_dig
                    ON p_dig.tenant_id = %s::uuid
                   AND NULLIF(t.digitador_number, '') IS NOT NULL
                   AND (
                        p_dig.number = t.digitador_number
                        OR ltrim(p_dig.number, '0') = ltrim(t.digitador_number, '0')
                   )
                LEFT JOIN users dig_u
                    ON dig_u.tenant_id = %s::uuid
                   AND dig_u.is_deleted = false
                   AND p_dig.id IS NOT NULL
                   AND (
                        (
                            NULLIF(p_dig.email, '') IS NOT NULL
                            AND lower(dig_u.email) = lower(p_dig.email)
                        )
                        OR dig_u.full_name = p_dig.name
                   )
            ),
            upsert AS (
                INSERT INTO cards (
                    tenant_id, hoj_num, hoj_fec, id_ambiente, id_ccosto, id_usuario,
                    id_inventariador, id_digitador,
                    state, hoj_can_tot, flag_firma,
                    nota_interna, nota_ficha
                )
                SELECT
                    %s::uuid,
                    NULLIF(regexp_replace(trim(r.hoj_num), '[^0-9]', '', 'g'), '')::bigint,
                    r.hoj_fec,
                    r.id_ambiente,
                    r.id_ccosto,
                    r.id_usuario,
                    r.id_inventariador,
                    r.id_digitador,
                    1,
                    0,
                    false,
                    NULLIF(trim(r.nota_interna), ''),
                    NULLIF(trim(r.nota_ficha), '')
                FROM resolved r
                ON CONFLICT (tenant_id, hoj_num) DO UPDATE SET
                    hoj_fec = EXCLUDED.hoj_fec,
                    id_ambiente = EXCLUDED.id_ambiente,
                    id_ccosto = EXCLUDED.id_ccosto,
                    id_usuario = EXCLUDED.id_usuario,
                    id_inventariador = EXCLUDED.id_inventariador,
                    id_digitador = EXCLUDED.id_digitador,
                    nota_interna = COALESCE(NULLIF(trim(EXCLUDED.nota_interna), ''), cards.nota_interna),
                    nota_ficha = COALESCE(NULLIF(trim(EXCLUDED.nota_ficha), ''), cards.nota_ficha),
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
            LEFT JOIN persons p_inv
              ON p_inv.tenant_id = %s::uuid
             AND (
                  p_inv.number = t.inventariador_number
                  OR ltrim(p_inv.number, '0') = ltrim(t.inventariador_number, '0')
             )
            LEFT JOIN users inv_u
              ON inv_u.tenant_id = %s::uuid
             AND inv_u.is_deleted = false
             AND p_inv.id IS NOT NULL
             AND (
                  (
                      NULLIF(p_inv.email, '') IS NOT NULL
                      AND lower(inv_u.email) = lower(p_inv.email)
                  )
                  OR inv_u.full_name = p_inv.name
             )
            WHERE env.id IS NULL OR cc.id IS NULL OR inv_u.id IS NULL
            """,
            (tenant_s, tenant_s, tenant_s, tenant_s),
        )
        unresolved = int(cur.fetchone()[0] or 0)
        if unresolved > 0:
            msg = (
                f"{unresolved} fila(s) no importada(s): ambiente, centro de costo "
                f"o inventariador (persona/usuario) no encontrado(s)."
            )
            if len(warnings) < MAX_IMPORT_WARNINGS:
                warnings.append(msg)

        if progress_cb:
            progress_cb(90, int(registered), int(updated), int(inserted))

        db.commit()

        from app.modules.inventory.dashboard_establishment_stats_cache import (
            flush_dashboard_stats_batch,
        )
        from app.modules.inventory.dashboard_establishment_stats_incremental import (
            DashboardStatsBatchCollector,
            collect_cards_ambiente_move_deltas,
        )

        stats_batch = DashboardStatsBatchCollector()
        stats_batch.merge_deltas(collect_cards_ambiente_move_deltas(db, tenant_id))
        flush_dashboard_stats_batch(tenant_id, stats_batch)

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
