"""PDF de resultados de importación masiva (conciliación / desconciliación)."""

from __future__ import annotations

import io
import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
MARGIN = 14 * mm
LIMA_TZ = ZoneInfo("America/Lima")


def _esc(value: object) -> str:
    s = str(value or "").strip()
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cell(value: object) -> str:
    s = str(value or "").strip()
    return s if s else "—"


def _safe_filename(title: str) -> str:
    base = re.sub(r"[^\w.-]+", "_", title.strip(), flags=re.UNICODE).strip("_")
    stamp = datetime.now(LIMA_TZ).strftime("%Y%m%d_%H%M%S")
    return (base[:80] or "reporte_importacion") + f"_{stamp}.pdf"


def _row_values(row: dict[str, Any], *, include_sbn: bool, include_ord: bool, with_message: bool) -> list[str]:
    values = [_cell(row.get("codigo_interno")), _cell(row.get("inv_num"))]
    if include_sbn:
        values.append(_cell(row.get("mar_cpat")))
    if include_ord:
        values.append(_cell(row.get("ord_conciliacion")))
    if with_message:
        values.append(_cell(row.get("message")))
    return values


def build_conciliation_import_report_pdf(
    *,
    title: str,
    message: str,
    registrados: list[dict[str, Any]],
    no_registrados: list[dict[str, Any]],
    include_sbn_column: bool = True,
    include_ord_column: bool = True,
) -> tuple[bytes, str]:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN,
    )

    title_style = ParagraphStyle(
        "Title",
        fontName=FONT_BOLD,
        fontSize=14,
        alignment=TA_CENTER,
        spaceAfter=6,
    )
    meta_style = ParagraphStyle(
        "Meta",
        fontName=FONT,
        fontSize=9,
        alignment=TA_LEFT,
        spaceAfter=4,
    )
    section_style = ParagraphStyle(
        "Section",
        fontName=FONT_BOLD,
        fontSize=10,
        alignment=TA_LEFT,
        spaceBefore=8,
        spaceAfter=4,
    )

    story: list[Any] = []
    now = datetime.now(LIMA_TZ).strftime("%d/%m/%Y %H:%M")
    story.append(Paragraph(_esc(title), title_style))
    story.append(Paragraph(f"Generado: {_esc(now)}", meta_style))
    if message.strip():
        story.append(Paragraph(f"Resumen: {_esc(message)}", meta_style))
    story.append(
        Paragraph(
            f"Procesados: {len(registrados)} · Errores: {len(no_registrados)}",
            meta_style,
        )
    )
    story.append(Spacer(1, 4 * mm))

    headers = ["Código interno", "Número inventario"]
    if include_sbn_column:
        headers.append("SBN")
    if include_ord_column:
        headers.append("Orden")
    error_headers = [*headers, "Mensaje"]

    def _table(data: list[list[str]], col_count: int) -> Table:
        usable_w = landscape(A4)[0] - 2 * MARGIN
        base_cols = 2 + int(include_sbn_column) + int(include_ord_column)
        if col_count > base_cols:
            widths = [usable_w * 0.14, usable_w * 0.12]
            if include_sbn_column:
                widths.append(usable_w * 0.14)
            if include_ord_column:
                widths.append(usable_w * 0.08)
            widths.append(usable_w - sum(widths))
        else:
            part = usable_w / col_count
            widths = [part] * col_count
        tbl = Table(data, colWidths=widths, repeatRows=1)
        tbl.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF4")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1a1a1a")),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CCCCCC")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFA")]),
                ]
            )
        )
        return tbl

    story.append(Paragraph(f"Registros procesados ({len(registrados)})", section_style))
    ok_rows = [headers]
    ok_rows.extend(
        _row_values(r, include_sbn=include_sbn_column, include_ord=include_ord_column, with_message=False)
        for r in registrados
    )
    if len(ok_rows) == 1:
        ok_rows.append(["—"] * len(headers))
    story.append(_table(ok_rows, len(headers)))

    story.append(Paragraph(f"Registros con error ({len(no_registrados)})", section_style))
    err_rows = [error_headers]
    err_rows.extend(
        _row_values(r, include_sbn=include_sbn_column, include_ord=include_ord_column, with_message=True)
        for r in no_registrados
    )
    if len(err_rows) == 1:
        err_rows.append(["—"] * len(error_headers))
    story.append(_table(err_rows, len(error_headers)))

    doc.build(story)
    return buf.getvalue(), _safe_filename(title)
