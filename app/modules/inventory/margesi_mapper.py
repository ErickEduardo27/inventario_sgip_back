"""Mapeo importación / escritura / lectura de ``margesi`` (columnas físicas)."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.inventory.margesi_fields import (
    EXTRA_KEY_TO_COLUMN,
    MARGESI_DATE_COLS,
    MARGESI_DECIMAL_COLS,
    MARGESI_ENUM_COLS,
    MARGESI_INT_COLS,
    MARGESI_STRING_MAX,
    all_margesi_column_names,
)

# Alineado a ``MARGESI_IMPORT_HEADERS`` (front), 108 columnas por índice.
IMPORT_COLUMN_BY_INDEX: tuple[str, ...] = (
    "mar_nant",
    "mar_num",
    "mar_npri",
    "mar_ccat",
    "mar_cpat",
    "mar_des",
    "mar_esp",
    "mar_est",
    "mar_uso",
    "mar_seg",
    "mar_col",
    "mar_mar",
    "mar_mod",
    "mar_ser",
    "mar_med",
    "mar_tip",
    "mar_npla",
    "mar_nmot",
    "mar_ncha",
    "mar_ano",
    "mar_obs",
    "mar_eti",
    "mar_flag",
    "mar_foto",
    "mar_foto2",
    "amb_cod",
    "usu_cod",
    "usu_resp_cod",
    "cct_cod",
    "mar_sit_conta",
    "mar_ing_tip",
    "mar_ing_fuente",
    "mar_ing_gasto",
    "mar_ing_siaf",
    "mar_ing_dini",
    "mar_ing_fdini",
    "mar_ing_dadq",
    "mar_ing_fdadq",
    "mar_ing_ding",
    "mar_ing_fding",
    "mar_ing_val",
    "mar_ing_vdep",
    "mar_ing_vutil",
    "mar_ing_pdep",
    "mar_ing_edad",
    "mar_ing_cta",
    "mar_ing_dasi",
    "mar_ing_fdasi",
    "mar_tas_doc",
    "mar_tas_fec",
    "mar_tas_val",
    "mar_tas_vutil",
    "mar_rev_doc",
    "mar_rev_fec",
    "mar_rev_vutil",
    "mar_rev_pdep",
    "mar_rev_edad",
    "mar_rev_vdep",
    "mar_cont_doc",
    "mar_cont_fec",
    "mar_cont_val",
    "mar_cont_cta",
    "mar_cont_vutil",
    "mar_cont_pdep",
    "mar_cont_edad",
    "mar_cont_depm",
    "mar_dep_hist",
    "mar_net_hist",
    "mar_dep_m01",
    "mar_dep_m02",
    "mar_dep_m03",
    "mar_dep_m04",
    "mar_dep_m05",
    "mar_dep_m06",
    "mar_dep_m07",
    "mar_dep_m08",
    "mar_dep_m09",
    "mar_dep_m10",
    "mar_dep_m11",
    "mar_dep_m12",
    "mar_dep_m13",
    "mar_dep_acum",
    "mar_net_val",
    "mar_sit_gral",
    "mar_baj_causal",
    "mar_baj_res",
    "mar_baj_fres",
    "mar_baj_tdisp",
    "mar_baj_rdis",
    "mar_baj_fdis",
    "mar_baj_benef",
    "mar_baj_elim_x",
    "inv_num",
    "inv_hoj",
    "inv_sit",
    "inv_con",
    "inv_num_1",
    "inv_num_2",
    "inv_sit_ant",
    "inv_ver_sit",
    "inv_ver_fecha",
    "inv_ver_obs",
    "user_create",
    "local_libre",
    "ccosto_libre",
    "campo_libre",
    "ambiente_libre",
    "usuario_libre",
)

IMPORT_EXCEL_DATE_INDEXES = frozenset({59})  # solo ``mar_cont_fec`` convierte serial Excel

_EXTRA_ONLY_KEYS = frozenset({"list_sbn_id", "cat_ultimo", "flag_depreciacion", "contabilidad"})

_PHYSICAL_COLS = frozenset(all_margesi_column_names())


def _blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and str(value) == "nan":
        return True
    return not str(value).strip()


def _str_val(value: object) -> str | None:
    if _blank(value):
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        return str(value).strip()
    return str(value).strip()


def _int_val(value: object) -> int | None:
    s = _str_val(value)
    if not s:
        return None
    digits = "".join(c for c in s if c.isdigit())
    if not digits:
        return None
    try:
        return int(digits)
    except ValueError:
        return None


def _decimal_val(value: object) -> Decimal | None:
    if _blank(value):
        return None
    if isinstance(value, Decimal):
        return value
    s = _str_val(value)
    if not s:
        return None
    s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _excel_serial_to_date(value: object) -> date | None:
    if _blank(value):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        n = float(value)
        if n <= 0:
            return None
        try:
            return (datetime(1899, 12, 30) + timedelta(days=n)).date()
        except (OverflowError, ValueError):
            return None
    s = _str_val(value)
    if not s:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _enum_val(name: str, value: object) -> str | None:
    s = (_str_val(value) or "").upper()[:1]
    if not s:
        return None
    allowed = next((vals for n, vals, _d in MARGESI_ENUM_COLS if n == name), ())
    return s if s in allowed else None


def coerce_column_value(col: str, value: object, *, excel_date: bool = False) -> Any:
    if _blank(value):
        return None
    if col in {e[0] for e in MARGESI_ENUM_COLS}:
        return _enum_val(col, value)
    if col in MARGESI_INT_COLS:
        return _int_val(value)
    if col in MARGESI_DATE_COLS:
        if excel_date:
            return _excel_serial_to_date(value)
        parsed = _excel_serial_to_date(value)
        if parsed:
            return parsed
        s = _str_val(value)
        if s:
            try:
                return date.fromisoformat(s[:10])
            except ValueError:
                return None
        return None
    if col in MARGESI_DECIMAL_COLS:
        return _decimal_val(value)
    s = _str_val(value)
    if s is None:
        return None
    max_len = MARGESI_STRING_MAX.get(col)
    if max_len and len(s) > max_len:
        return s[:max_len]
    return s


def import_cells_to_values(cells: list[object]) -> dict[str, Any]:
    """Convierte 108 celdas a dict de columnas físicas (sin persistir)."""
    from app.modules.inventory import models as m

    row = m.InvMargesiItem()
    apply_import_cells(row, cells)
    values: dict[str, Any] = {}
    for col in _PHYSICAL_COLS:
        if hasattr(row, col):
            values[col] = getattr(row, col)
    return values


def apply_import_cells(row: Any, cells: list[object]) -> str:
    """Aplica 108 celdas al modelo; devuelve ``mar_num`` para upsert."""
    mar_num = ""
    for idx, col in enumerate(IMPORT_COLUMN_BY_INDEX):
        if idx >= len(cells):
            break
        if col == "mar_num":
            mar_num = _str_val(cells[idx]) or ""
        excel_date = idx in IMPORT_EXCEL_DATE_INDEXES
        val = coerce_column_value(col, cells[idx], excel_date=excel_date)
        if val is not None and hasattr(row, col):
            setattr(row, col, val)
    for name, _vals, default in MARGESI_ENUM_COLS:
        if hasattr(row, name) and not getattr(row, name, None):
            setattr(row, name, default)
    return mar_num.strip()


def flatten_write_payload(data: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Separa campos físicos y claves que permanecen en ``extra`` JSONB."""
    extra = dict(data.pop("extra", None) or {})
    conta = extra.pop("contabilidad", None)
    if isinstance(conta, dict):
        for k, v in conta.items():
            if k not in extra:
                extra[k] = v
    physical: dict[str, Any] = {}
    leftover: dict[str, Any] = {}
    for key, val in {**data, **extra}.items():
        if key in _EXTRA_ONLY_KEYS:
            leftover[key] = val
            continue
        col = EXTRA_KEY_TO_COLUMN.get(key, key if key in _PHYSICAL_COLS else None)
        if col:
            physical[col] = val
        elif key in _PHYSICAL_COLS:
            physical[key] = val
        else:
            leftover[key] = val
    return physical, leftover


def apply_write_payload(row: Any, data: dict[str, Any]) -> None:
    physical, leftover = flatten_write_payload(dict(data))
    for col, raw in physical.items():
        if not hasattr(row, col):
            continue
        excel_date = col == "mar_cont_fec"
        val = coerce_column_value(col, raw, excel_date=excel_date)
        setattr(row, col, val)
    row.extra = leftover or None


def margesi_row_to_api(row: Any) -> dict[str, Any]:
    """Dict plano para API (incluye alias legacy en ``extra`` mínimo)."""
    from sqlalchemy import inspect as sa_inspect

    d: dict[str, Any] = {}
    for attr in sa_inspect(row).mapper.column_attrs:
        val = getattr(row, attr.key)
        if hasattr(val, "isoformat"):
            d[attr.key] = val.isoformat()
        else:
            d[attr.key] = val
    leftover = d.get("extra") if isinstance(d.get("extra"), dict) else {}
    d["mar_num"] = d.get("mar_num") or leftover.get("codigo_interno")
    d["codigo_interno"] = d.get("mar_num")
    if leftover:
        d["extra"] = leftover
    else:
        d.pop("extra", None)
    return d
