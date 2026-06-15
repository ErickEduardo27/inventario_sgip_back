"""Zona horaria de Perú (America/Lima) para fechas de negocio."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any
from zoneinfo import ZoneInfo

PERU_TZ = ZoneInfo("America/Lima")


def day_start_pe(d: date) -> datetime:
    """Inicio del día calendario en Perú (00:00:00 -05)."""
    return datetime.combine(d, time.min, tzinfo=PERU_TZ)


def day_end_pe(d: date) -> datetime:
    """Fin del día calendario en Perú (23:59:59.999999 -05)."""
    return datetime.combine(d, time.max, tzinfo=PERU_TZ)


def to_peru(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PERU_TZ)


def format_datetime_pe(dt: datetime | None) -> str | None:
    """Formato legible dd/mm/yyyy HH:MM en hora de Perú."""
    pe = to_peru(dt)
    if pe is None:
        return None
    return pe.strftime("%d/%m/%Y %H:%M")


def enrich_pe_timestamps(row: dict[str, Any]) -> dict[str, Any]:
    """Añade ``created_at_pe`` y ``updated_at_pe`` a filas del inventario."""
    for key in ("created_at", "updated_at"):
        val = row.get(key)
        if not val:
            continue
        try:
            if isinstance(val, str):
                dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            elif isinstance(val, datetime):
                dt = val
            else:
                continue
            row[f"{key}_pe"] = format_datetime_pe(dt)
        except (ValueError, TypeError):
            continue
    return row
