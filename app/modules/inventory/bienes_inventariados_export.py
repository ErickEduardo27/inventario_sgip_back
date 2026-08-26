"""Generación del Excel de bienes inventariados."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from app.modules.inventory.csv_export import copy_query_to_csv_bytes
from app.modules.inventory.excel_styled_export import (
    BIENES_INVENTARIADOS_COLUMN_FORMATS,
    csv_bytes_to_styled_xlsx_bytes,
)
from app.modules.inventory.export_queries import build_item_cards_export_query
from app.modules.inventory.schemas import RecordQuery
from app.modules.tenants.theme import primary_hex_openpyxl


def build_bienes_inventariados_xlsx_bytes(tenant_id: UUID, q: RecordQuery) -> tuple[bytes, str]:
    """Construye XLSX estilizado de bienes inventariados."""
    inner_sql, params, filename_base = build_item_cards_export_query(tenant_id, q)
    payload = copy_query_to_csv_bytes(inner_sql, params)
    header_color = primary_hex_openpyxl(tenant_id)
    content = csv_bytes_to_styled_xlsx_bytes(
        payload,
        column_formats=BIENES_INVENTARIADOS_COLUMN_FORMATS,
        sheet_title="Bienes inventariados",
        header_color_hex=header_color,
    )
    filename = f"{filename_base}_{date.today().isoformat()}.xlsx"
    return content, filename
