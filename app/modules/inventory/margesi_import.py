"""Importación masiva Margesi (ItemsImport legacy).

Fila 1 = cabecera (descartada). Columnas A–DE por índice (108 campos, 0–107).
Upsert por ``mar_num`` (columna B): create y update incrementan ``registered``.
Sin validación de negocio; no actualiza ``list_sbn.cat_ulti``.
Solo ``mar_cont_fec`` (índice 59) convierte serial numérico Excel a fecha.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.inventory import models as m
from app.modules.inventory.bulk_copy import (
    copy_dataframe_csv,
    ensure_staging_table,
    truncate_staging,
)
from app.modules.inventory.margesi_fields import (
    MARGESI_DATE_COLS,
    MARGESI_DECIMAL_COLS,
    MARGESI_INT_COLS,
    all_margesi_column_names,
)
from app.modules.inventory.margesi_mapper import import_cells_to_values

MARGESI_IMPORT_COLS = 108
UPSERT_COL_INDEX = 1
MARGESI_CHUNK_SIZE = 20_000
_MARGESI_BULK_COLS = [c for c in all_margesi_column_names() if c != "extra"]
_STAGING_TABLE = "tmp_margesi_staging"

_MOMENT_COLS = ("local_libre", "campo_libre", "ambiente_libre", "usuario_libre", "ccosto_libre")
_MOMENT_SOURCE_INDEX = (2, 3, 4, 5, 6)


def _cell_str(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()
    return str(value).strip()


def _normalize_raw_chunk(df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    if n == 0:
        return pd.DataFrame({i: pd.Series(dtype=str) for i in range(MARGESI_IMPORT_COLS)})
    cols: dict[int, pd.Series] = {}
    width = df.shape[1]
    for i in range(MARGESI_IMPORT_COLS):
        if i < width:
            cols[i] = df.iloc[:, i].astype(str)
        else:
            cols[i] = pd.Series([""] * n, index=df.index, dtype=str)
    return pd.DataFrame(cols)


def _read_raw_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return pd.read_csv(io.StringIO(text), header=None, dtype=str, keep_default_na=False)
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content), header=None, dtype=str, keep_default_na=False)
    raise ValueError("Formato no soportado. Use .xlsx, .xls o .csv")


def _iter_margesi_data_chunks(content: bytes, filename: str) -> Iterator[tuple[pd.DataFrame, int]]:
    lower = filename.lower()
    if lower.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        total_in_file = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
        if total_in_file < 2:
            raise ValueError("El archivo no contiene filas de datos (se requiere encabezado + al menos una fila)")

        reader = pd.read_csv(
            io.StringIO(text),
            header=None,
            dtype=str,
            keep_default_na=False,
            chunksize=MARGESI_CHUNK_SIZE,
        )
        skip_header = True
        for raw in reader:
            if skip_header:
                raw = raw.iloc[1:]
                skip_header = False
            if raw.empty:
                continue
            yield _normalize_raw_chunk(raw), total_in_file
        return

    if lower.endswith((".xlsx", ".xls")):
        raw = pd.read_excel(io.BytesIO(content), header=None, dtype=str, keep_default_na=False)
        total_in_file = int(len(raw))
        if total_in_file < 2:
            raise ValueError("El archivo no contiene filas de datos (se requiere encabezado + al menos una fila)")

        data = _normalize_raw_chunk(raw.iloc[1:])
        for start in range(0, len(data), MARGESI_CHUNK_SIZE):
            yield data.iloc[start : start + MARGESI_CHUNK_SIZE].copy(), total_in_file
        return

    raise ValueError("Formato no soportado. Use .xlsx, .xls o .csv")


def parse_margesi_data_rows(content: bytes, filename: str) -> tuple[pd.DataFrame, int]:
    """Carga completa en memoria (p. ej. validaciones en router)."""
    raw = _read_raw_dataframe(content, filename)
    total_in_file = int(len(raw))
    if raw.empty or total_in_file < 2:
        raise ValueError("El archivo no contiene filas de datos (se requiere encabezado + al menos una fila)")
    return _normalize_raw_chunk(raw.iloc[1:]), total_in_file


def _serialize_margesi_value(value: object) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _map_chunk_to_staging(chunk: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Convierte filas crudas (0..107) a columnas físicas listas para COPY."""
    n = len(chunk)
    if n == 0:
        return pd.DataFrame(columns=cols)

    arr = chunk.to_numpy(dtype=object)
    width = arr.shape[1]
    rows: list[list[str]] = []
    for i in range(n):
        cells = [arr[i, j] if j < width else None for j in range(MARGESI_IMPORT_COLS)]
        values = import_cells_to_values(cells)
        rows.append([_serialize_margesi_value(values.get(c)) for c in cols])
    return pd.DataFrame(rows, columns=cols)


def _split_staging_for_load(staging: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    mar_key = staging["mar_num"].astype(str).str.strip()
    without_mar = staging.loc[mar_key == ""]
    with_mar = staging.loc[mar_key != ""].copy()
    if not with_mar.empty:
        with_mar["mar_num"] = with_mar["mar_num"].astype(str).str.strip()
        with_mar = with_mar.drop_duplicates(subset=["mar_num"], keep="last")
    return with_mar, without_mar


def _margesi_sql_expr(col: str) -> str:
    if col in MARGESI_DATE_COLS:
        return f"NULLIF(NULLIF(TRIM(t.{col}), ''), 'null')::date"
    if col in MARGESI_DECIMAL_COLS:
        return f"NULLIF(NULLIF(TRIM(t.{col}), ''), 'null')::numeric"
    if col in MARGESI_INT_COLS and col in ("inv_num_1", "inv_num_2"):
        return f"NULLIF(NULLIF(TRIM(t.{col}), ''), 'null')::bigint"
    return f"NULLIF(t.{col}, '')"


def _upsert_from_staging(cur, *, tenant_s: str, cols: list[str], cols_sql: str, select_sql: str, update_sql: str) -> None:
    cur.execute(
        f"""
        INSERT INTO margesi (tenant_id, {cols_sql})
        SELECT %s::uuid, {select_sql}
        FROM {_STAGING_TABLE} t
        WHERE NULLIF(TRIM(t.mar_num), '') IS NOT NULL
        ON CONFLICT (tenant_id, mar_num)
        WHERE mar_num IS NOT NULL AND TRIM(mar_num) <> ''
        DO UPDATE SET
            {update_sql},
            updated_at = NOW()
        """,
        (tenant_s,),
    )


def _insert_without_mar_num_from_staging(cur, *, tenant_s: str, cols_sql: str, select_sql: str) -> None:
    cur.execute(
        f"""
        INSERT INTO margesi (tenant_id, {cols_sql})
        SELECT %s::uuid, {select_sql}
        FROM {_STAGING_TABLE} t
        WHERE NULLIF(TRIM(t.mar_num), '') IS NULL
        """,
        (tenant_s,),
    )


def bulk_import_margesi(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    progress_cb=None,
) -> dict[str, Any]:
    tenant_s = str(tenant_id)
    cols = _MARGESI_BULK_COLS
    cols_sql = ", ".join(cols)
    select_sql = ", ".join(_margesi_sql_expr(c) for c in cols)
    update_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in cols if c != "mar_num")
    temp_cols_ddl = ", ".join(f"{c} TEXT" for c in cols)

    raw_conn = db.connection().connection
    cur = raw_conn.cursor()
    registered = 0
    total_in_file = 0
    data_row_target = 1
    saw_data = False

    try:
        ensure_staging_table(cur, table_name=_STAGING_TABLE, columns_ddl=temp_cols_ddl)

        data_row_target = max(total_in_file - 1, 1)

        for raw_chunk, file_total in _iter_margesi_data_chunks(content, filename):
            saw_data = True
            total_in_file = file_total
            data_row_target = max(total_in_file - 1, 1)
            chunk_rows = len(raw_chunk)

            staging = _map_chunk_to_staging(raw_chunk, cols)
            upsert_df, null_df = _split_staging_for_load(staging)

            if not upsert_df.empty:
                truncate_staging(cur, _STAGING_TABLE)
                copy_dataframe_csv(cur, table_name=_STAGING_TABLE, columns=cols, df=upsert_df)
                _upsert_from_staging(
                    cur,
                    tenant_s=tenant_s,
                    cols=cols,
                    cols_sql=cols_sql,
                    select_sql=select_sql,
                    update_sql=update_sql,
                )

            if not null_df.empty:
                truncate_staging(cur, _STAGING_TABLE)
                copy_dataframe_csv(cur, table_name=_STAGING_TABLE, columns=cols, df=null_df)
                _insert_without_mar_num_from_staging(
                    cur,
                    tenant_s=tenant_s,
                    cols_sql=cols_sql,
                    select_sql=select_sql,
                )

            registered += chunk_rows
            if progress_cb:
                pct = min(99, int(registered * 100 / data_row_target))
                progress_cb(pct, data_row_target, 0, registered)

        if not saw_data:
            return {
                "success": False,
                "message": "No hay filas para importar",
                "total": total_in_file,
                "registered": 0,
                "errors": ["Archivo sin filas de datos"],
            }

        db.commit()
        if progress_cb:
            progress_cb(100, data_row_target, 0, registered)

        return {
            "success": True,
            "message": f"Importación completada: {registered} fila(s) procesada(s)",
            "total": total_in_file,
            "registered": registered,
            "inserted": registered,
            "updated": 0,
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {
            "success": False,
            "message": "Error al importar Margesi",
            "total": total_in_file,
            "registered": registered,
            "errors": [str(exc)],
        }
    finally:
        cur.close()


def process_margesi_upload(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    progress_cb=None,
) -> dict[str, Any]:
    return bulk_import_margesi(
        db, tenant_id, content, filename, progress_cb=progress_cb
    )


def parse_margesi_moment_rows(content: bytes, filename: str) -> tuple[pd.DataFrame, int]:
    raw = _read_raw_dataframe(content, filename)
    total_in_file = int(len(raw))
    if raw.empty or total_in_file < 2:
        raise ValueError("El archivo no contiene filas de datos (se requiere encabezado + al menos una fila)")

    data = raw.iloc[1:].copy()
    ncol = min(7, data.shape[1])
    rename = {data.columns[i]: i for i in range(ncol)}
    data = data.rename(columns=rename)
    for i in range(ncol, 7):
        data[i] = ""
    return data[list(range(7))], total_in_file


def _inv_num_1_index(db: Session, tenant_id: UUID) -> dict[str, m.InvMargesiItem]:
    index: dict[str, m.InvMargesiItem] = {}
    rows = db.scalars(select(m.InvMargesiItem).where(m.InvMargesiItem.tenant_id == tenant_id)).all()
    for row in rows:
        if row.inv_num_1 is None:
            continue
        code = str(row.inv_num_1).strip()
        if code and code not in index:
            index[code] = row
    return index


def process_margesi_moment_upload(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    progress_cb=None,
) -> dict[str, Any]:
    df, total_in_file = parse_margesi_moment_rows(content, filename)
    registered = 0
    inv_index = _inv_num_1_index(db, tenant_id)

    try:
        arr = df.to_numpy(dtype=object)
        width = arr.shape[1]
        for i in range(len(df)):
            cells = [_cell_str(arr[i, j] if j < width else None) for j in range(7)]
            key = cells[0].strip()
            if not key:
                continue
            existing = inv_index.get(key)
            if not existing:
                continue

            for attr, src_i in zip(_MOMENT_COLS, _MOMENT_SOURCE_INDEX, strict=True):
                val = cells[src_i].strip()
                setattr(existing, attr, val or None)
            db.add(existing)
            registered += 1
            db.commit()

        return {
            "success": True,
            "message": f"Importación momento: {registered} fila(s) actualizada(s)",
            "total": total_in_file,
            "registered": registered,
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {
            "success": False,
            "message": "Error al importar momento Margesi",
            "total": total_in_file,
            "registered": 0,
            "errors": [str(exc)],
        }
