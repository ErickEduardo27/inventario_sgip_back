"""Importación masiva de bienes en hojas de captura (itemcards).

Fila 1 = cabecera. Columnas A–N por índice:
  hoj_num, inv_num, mar_col, mar_mar, mar_mod, mar_ser, mar_med, mar_des,
  inv_num_1, inv_num_2, mar_num, mar_cpat, mar_cpat_num, id_margesi.

La hoja debe existir (``cards.hoj_num``). Upsert por ``inv_num`` dentro del tenant:
actualiza si el bien ya está en la misma hoja; omite con error si ``inv_num`` está en otra hoja.
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
from app.modules.inventory.schemas import CardItemWrite
from app.modules.inventory.service import recount_card_items, store_card_item

IMPORT_COLS = 14
CHUNK_SIZE = 2_000

_IMPORT_FIELD_NAMES = (
    "hoj_num",
    "inv_num",
    "mar_col",
    "mar_mar",
    "mar_mod",
    "mar_ser",
    "mar_med",
    "mar_des",
    "inv_num_1",
    "inv_num_2",
    "mar_num",
    "mar_cpat",
    "mar_cpat_num",
    "id_margesi",
)


def _cell_str(value: object) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()
    return str(value).strip()


def _read_raw_dataframe(content: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    if lower.endswith(".csv"):
        text = content.decode("utf-8-sig", errors="replace")
        return pd.read_csv(io.StringIO(text), header=None, dtype=str, keep_default_na=False)
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(content), header=None, dtype=str, keep_default_na=False)
    raise ValueError("Formato no soportado. Use .xlsx, .xls o .csv")


def _normalize_raw_chunk(df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    if n == 0:
        return pd.DataFrame({i: pd.Series(dtype=str) for i in range(IMPORT_COLS)})
    cols: dict[int, pd.Series] = {}
    width = df.shape[1]
    for i in range(IMPORT_COLS):
        if i < width:
            cols[i] = df.iloc[:, i].astype(str)
        else:
            cols[i] = pd.Series([""] * n, index=df.index, dtype=str)
    return pd.DataFrame(cols)


def _iter_data_chunks(content: bytes, filename: str) -> Iterator[tuple[pd.DataFrame, int]]:
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
            chunksize=CHUNK_SIZE,
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

    raw = _read_raw_dataframe(content, filename)
    total_in_file = int(len(raw))
    if total_in_file < 2:
        raise ValueError("El archivo no contiene filas de datos (se requiere encabezado + al menos una fila)")
    data = _normalize_raw_chunk(raw.iloc[1:])
    for start in range(0, len(data), CHUNK_SIZE):
        yield data.iloc[start : start + CHUNK_SIZE].copy(), total_in_file


def parse_hoja_captura_item_rows(content: bytes, filename: str) -> tuple[pd.DataFrame, int]:
    raw = _read_raw_dataframe(content, filename)
    total_in_file = int(len(raw))
    if total_in_file < 2:
        raise ValueError("El archivo no contiene filas de datos (se requiere encabezado + al menos una fila)")
    return _normalize_raw_chunk(raw.iloc[1:]), total_in_file


def _card_index(db: Session, tenant_id: UUID) -> dict[str, m.InvCard]:
    rows = db.scalars(select(m.InvCard).where(m.InvCard.tenant_id == tenant_id)).all()
    index: dict[str, m.InvCard] = {}
    for row in rows:
        key = _normalize_hoj_num((row.hoj_num or "").strip())
        if key and key not in index:
            index[key] = row
    return index


def _inv_num_index(db: Session, tenant_id: UUID) -> dict[str, m.InvItemCard]:
    index: dict[str, m.InvItemCard] = {}
    rows = db.scalars(select(m.InvItemCard).where(m.InvItemCard.tenant_id == tenant_id)).all()
    for row in rows:
        key = (row.inv_num or "").strip()
        if key and key not in index:
            index[key] = row
    return index


def _row_to_body(row: pd.Series) -> CardItemWrite | None:
    hoj_num = _cell_str(row.get(0))
    inv_num = _cell_str(row.get(1))
    if not hoj_num or not inv_num:
        return None

    id_margesi_raw = _cell_str(row.get(13))
    id_margesi: int | None = None
    if id_margesi_raw.isdigit():
        id_margesi = int(id_margesi_raw)

    return CardItemWrite(
        inv_num=inv_num,
        mar_col=_cell_str(row.get(2)) or None,
        mar_mar=_cell_str(row.get(3)) or None,
        mar_mod=_cell_str(row.get(4)) or None,
        mar_ser=_cell_str(row.get(5)) or None,
        mar_med=_cell_str(row.get(6)) or None,
        mar_des=_cell_str(row.get(7)) or None,
        inv_num_1=_cell_str(row.get(8)) or None,
        inv_num_2=_cell_str(row.get(9)) or None,
        mar_num=_cell_str(row.get(10)) or None,
        mar_cpat=_cell_str(row.get(11)) or None,
        mar_cpat_num=_cell_str(row.get(12)) or "",
        id_margesi=id_margesi,
        no_conciliar=id_margesi is None,
    )


def _normalize_hoj_num(value: str) -> str:
    s = value.strip()
    if s.isdigit():
        return str(int(s)).zfill(5)
    return s


def bulk_import_hoja_captura_items(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    operator_id: UUID | None = None,
    progress_cb=None,
) -> dict[str, Any]:
    cards = _card_index(db, tenant_id)
    inv_index = _inv_num_index(db, tenant_id)
    registered = 0
    inserted = 0
    updated = 0
    skipped = 0
    errors: list[str] = []
    total_in_file = 0
    data_row_target = 1
    saw_data = False

    try:
        for chunk, file_total in _iter_data_chunks(content, filename):
            saw_data = True
            total_in_file = file_total
            data_row_target = max(total_in_file - 1, 1)

            for _, row in chunk.iterrows():
                hoj_num = _normalize_hoj_num(_cell_str(row.get(0)))
                body = _row_to_body(row)
                if body is None:
                    skipped += 1
                    continue

                card = cards.get(hoj_num)
                if card is None:
                    errors.append(f"Hoja {hoj_num} no encontrada")
                    if len(errors) >= 200:
                        break
                    skipped += 1
                    continue
                if int(card.state or 0) == 2:
                    errors.append(f"Hoja {hoj_num} cerrada; fila omitida (inv {body.inv_num})")
                    if len(errors) >= 200:
                        break
                    skipped += 1
                    continue

                existing = inv_index.get((body.inv_num or "").strip())
                if existing is not None:
                    if int(existing.id_card) != int(card.id):
                        errors.append(
                            f"N° inventario {body.inv_num} ya existe en otra hoja (fila hoj {hoj_num})"
                        )
                        if len(errors) >= 200:
                            break
                        skipped += 1
                        continue
                    body.id = int(existing.id)

                ok, msg = store_card_item(
                    db,
                    tenant_id,
                    int(card.id),
                    body,
                    operator_id=operator_id if not body.id else None,
                )
                if not ok:
                    errors.append(f"Hoja {hoj_num} / {body.inv_num}: {msg}")
                    if len(errors) >= 200:
                        break
                    skipped += 1
                    continue

                registered += 1
                if body.id:
                    updated += 1
                else:
                    inserted += 1
                    inv_key = (body.inv_num or "").strip()
                    if inv_key:
                        fresh = db.scalar(
                            select(m.InvItemCard).where(
                                m.InvItemCard.tenant_id == tenant_id,
                                m.InvItemCard.inv_num == inv_key,
                            )
                        )
                        if fresh is not None:
                            inv_index[inv_key] = fresh

            if progress_cb:
                pct = min(99, int(registered * 100 / max(data_row_target, 1)))
                progress_cb(pct, data_row_target, updated, inserted)

        if not saw_data:
            return {
                "success": False,
                "message": "No hay filas para importar",
                "total": total_in_file,
                "registered": 0,
                "inserted": 0,
                "updated": 0,
                "errors": ["Archivo sin filas de datos"],
            }

        recount_card_items(db, tenant_id)
        db.commit()

        if progress_cb:
            progress_cb(100, data_row_target, updated, inserted)

        ok = registered > 0 or not errors
        return {
            "success": ok,
            "message": f"Importación completada: {registered} bien(es) procesado(s)",
            "total": total_in_file,
            "registered": registered,
            "inserted": inserted,
            "updated": updated,
            "errors": errors[:200],
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return {
            "success": False,
            "message": "Error al importar bienes de hoja de captura",
            "total": total_in_file,
            "registered": registered,
            "inserted": inserted,
            "updated": updated,
            "errors": [str(exc), *errors[:50]],
        }


def process_hoja_captura_upload(
    db: Session,
    tenant_id: UUID,
    content: bytes,
    filename: str,
    *,
    progress_cb=None,
    operator_id: UUID | None = None,
) -> dict[str, Any]:
    return bulk_import_hoja_captura_items(
        db,
        tenant_id,
        content,
        filename,
        operator_id=operator_id,
        progress_cb=progress_cb,
    )
