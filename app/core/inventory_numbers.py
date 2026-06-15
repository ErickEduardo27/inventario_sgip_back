"""Normalización de números de hoja e inventario (enteros únicos por tenant)."""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import String, cast

_DIGITS = re.compile(r"[^0-9]+")


def parse_inventory_number(value: object, *, field: str = "Número", allow_empty: bool = False) -> int:
    """Convierte entrada a entero; rechaza valores no numéricos."""
    if value is None:
        if allow_empty:
            return 0
        raise ValueError(f"{field} obligatorio")
    if isinstance(value, bool):
        raise ValueError(f"{field} inválido")
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"{field} inválido")
        return value
    s = str(value).strip()
    if not s:
        if allow_empty:
            return 0
        raise ValueError(f"{field} obligatorio")
    digits = _DIGITS.sub("", s)
    if not digits:
        raise ValueError(f"{field} inválido: debe ser numérico")
    return int(digits)


def try_parse_inventory_number(value: object) -> int | None:
    try:
        return parse_inventory_number(value)
    except ValueError:
        return None


def format_hoj_num(value: int | None) -> str:
    return str(int(value or 0)).zfill(5)


def format_inv_num(value: int | None) -> str:
    if value is None:
        return ""
    return str(int(value))


def numeric_column_filter(column: Any, raw: str) -> Any:
    """Filtro por columna entera: igualdad si el valor es numérico; si no, ``ILIKE`` sobre texto."""
    s = (raw or "").strip()
    if not s:
        return column.is_(None)
    parsed = try_parse_inventory_number(s)
    if parsed is not None:
        return column == parsed
    return cast(column, String).ilike(f"%{s}%")


def numeric_column_ilike(column: Any, pattern: str) -> Any:
    """``ILIKE`` sobre columna entera (patrón con ``%``)."""
    return cast(column, String).ilike(pattern)
