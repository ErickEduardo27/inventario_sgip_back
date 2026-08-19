"""PDF «Anexo 005 – Acta de Cierre» para Reporte Locales."""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PAGE_W, PAGE_H = A4
MARGIN_L = 18 * mm
MARGIN_R = 18 * mm
MARGIN_T = 14 * mm
MARGIN_B = 14 * mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
BORDER = 0.75
LINE_COLOR = colors.HexColor("#333333")

_SPANISH_MONTHS = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def _esc(value: object) -> str:
    s = str(value or "").strip()
    if not s:
        return "……………………"
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cell(value: object, *, empty: str = "") -> str:
    s = str(value or "").strip()
    return s if s else empty


def _format_acta_date(value: date | str | None) -> tuple[str, str, str]:
    if isinstance(value, str):
        raw = value.strip()
        if raw:
            try:
                value = date.fromisoformat(raw[:10])
            except ValueError:
                value = None
    d = value if isinstance(value, date) else date.today()
    day = str(d.day)
    month = _SPANISH_MONTHS[d.month - 1] if 1 <= d.month <= 12 else str(d.month)
    year = str(d.year)
    return day, month, year


def _safe_filename(code: str, description: str | None) -> str:
    base = f"acta_cierre_{code}_{description or 'local'}"
    safe = re.sub(r"[^\w.-]+", "_", base, flags=re.UNICODE).strip("_")
    return (safe[:120] or "acta_cierre") + ".pdf"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "acta_title",
            parent=base["Normal"],
            fontName=FONT_BOLD,
            fontSize=11,
            leading=13,
            alignment=TA_CENTER,
            spaceAfter=2,
        ),
        "subtitle": ParagraphStyle(
            "acta_subtitle",
            parent=base["Normal"],
            fontName=FONT_BOLD,
            fontSize=11,
            leading=13,
            alignment=TA_CENTER,
            spaceAfter=8,
        ),
        "body": ParagraphStyle(
            "acta_body",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=10,
            leading=14,
            alignment=TA_JUSTIFY,
            spaceAfter=8,
        ),
        "small": ParagraphStyle(
            "acta_small",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=9,
            leading=12,
            alignment=TA_LEFT,
        ),
        "center": ParagraphStyle(
            "acta_center",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=10,
            leading=12,
            alignment=TA_CENTER,
        ),
    }


def generate_acta_cierre_pdf(payload: dict[str, Any]) -> tuple[bytes, str]:
    """Genera bytes PDF y nombre de archivo a partir de datos ya resueltos."""
    st = _styles()
    code = _cell(payload.get("establishment_code"))
    description = _cell(payload.get("establishment_description"))
    day, month, year = _format_acta_date(payload.get("fecha"))
    hora = _cell(payload.get("hora"), empty="……")
    macro = _cell(payload.get("macroregion"))
    dept = _cell(payload.get("departamento"))
    prov = _cell(payload.get("provincia"))
    dist = _cell(payload.get("distrito"))
    oficina = _cell(payload.get("oficina_sede"), empty=description or "……………………")
    reps_banco = _cell(payload.get("representantes_banco"))
    rep_sertec = _cell(payload.get("representante_sertec"))
    sede_label = f"{code} - {description}".strip(" -") if description else code

    total_bd = int(payload.get("total_bd") or 0)
    conforme = int(payload.get("conforme") or 0)
    faltantes = int(payload.get("faltantes") or 0)
    sobrantes = int(payload.get("sobrantes") or 0)
    total_inv = int(payload.get("total_inventariados") or (conforme + sobrantes))

    bn_nombre = _cell(payload.get("bn_nombre"))
    bn_cargo = _cell(payload.get("bn_cargo"))
    bn_dni = _cell(payload.get("bn_dni"))
    sertec_nombre = _cell(payload.get("sertec_nombre"))
    sertec_cargo = _cell(payload.get("sertec_cargo"), empty="Inventariador")
    sertec_dni = _cell(payload.get("sertec_dni"))
    observaciones = _cell(payload.get("observaciones"))

    flow: list[Any] = [
        Paragraph(
            "SERVICIO DE TOMA DE INVENTARIO DE LOS BIENES MUEBLES DEL ACTIVO FIJO DEL BANCO DE LA NACION",
            st["title"],
        ),
        Paragraph("ACTA DE CIERRE", st["subtitle"]),
        Paragraph(
            f"SEDE ( {_esc(code)} ) &nbsp;&nbsp; {_esc(description or sede_label)}",
            st["center"],
        ),
        Spacer(1, 4),
    ]

    geo_table = Table(
        [
            ["Macroregión", "Departamento", "Provincia", "Distrito"],
            [_esc(macro), _esc(dept), _esc(prov), _esc(dist)],
        ],
        colWidths=[CONTENT_W * 0.25] * 4,
    )
    geo_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, 1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), BORDER, LINE_COLOR),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5E6D3")),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    flow.append(geo_table)
    flow.append(Spacer(1, 8))

    flow.append(
        Paragraph(
            (
                f"Siendo las {_esc(hora)} horas del día {_esc(day)} de {_esc(month)} del {year}, "
                f"en la Oficina de la Sede {_esc(oficina)}, se reunieron los señores "
                f"{_esc(reps_banco)}, en representación del BANCO DE LA NACION y de la otra parte "
                f"el Sr (srta) {_esc(rep_sertec)} en representación de la Empresa SERTEC Soluciones "
                f"Empresariales SAC, con el objeto de suscribir el Acta de Cierre del Inventario "
                f"Físico de Bienes Muebles de la Sede {_esc(sede_label)}."
            ),
            st["body"],
        )
    )
    flow.append(
        Paragraph(
            "El resultado del proceso de la conciliación preliminar realizado, de acuerdo a la existencia "
            "física de los bienes debidamente ubicados e identificados según las fichas de levantamiento "
            "de información, se distribuyen de la siguiente manera:",
            st["body"],
        )
    )

    stats_rows = [
        ["Conceptos", "Cantidad", "Observaciones"],
        ["Total bienes registrados en BD del Banco de la Nación", str(total_bd), ""],
        [
            "Bienes Conforme",
            str(conforme),
            "Bienes registrados en la base de datos de la sede ubicados",
        ],
        [
            "Bienes Faltantes",
            str(faltantes),
            "Bienes registrados en la base de datos de la sede no ubicados.",
        ],
        [
            "Bienes Sobrantes",
            str(sobrantes),
            "Bienes no registrados en la base de datos de la sede ubicados",
        ],
        ["Total de Bienes Inventariados", str(total_inv), ""],
    ]
    stats_table = Table(
        stats_rows,
        colWidths=[CONTENT_W * 0.42, CONTENT_W * 0.12, CONTENT_W * 0.46],
    )
    stats_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), BORDER, LINE_COLOR),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5E6D3")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    flow.append(stats_table)
    flow.append(Spacer(1, 8))

    flow.append(
        Paragraph(
            "La presente Acta de Cierre se firma en señal de conformidad dando fe de lo actuado, "
            "así como del resultado indicado.",
            st["body"],
        )
    )
    flow.append(
        Paragraph(
            "Los bienes Faltantes serán conciliados o buscados a nivel nacional.",
            st["body"],
        )
    )

    sign_rows = [
        ["BANCO DE LA NACION", "SERTEC"],
        ["Nombre", "Nombre"],
        [_esc(bn_nombre), _esc(sertec_nombre)],
        ["Cargo", "Cargo"],
        [_esc(bn_cargo), _esc(sertec_cargo)],
        ["Código/DNI", "DNI"],
        [_esc(bn_dni), _esc(sertec_dni)],
        ["(Firma y Sello)", "(Firma)"],
        ["", ""],
        ["", ""],
        ["", ""],
    ]
    sign_row_heights = [None] * 7 + [8 * mm, 16 * mm, 16 * mm, 16 * mm]
    sign_table = Table(
        sign_rows,
        colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5],
        rowHeights=sign_row_heights,
    )
    sign_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTNAME", (0, 1), (-1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, 6), "MIDDLE"),
                ("VALIGN", (0, 7), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), BORDER, LINE_COLOR),
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5E6D3")),
                ("TOPPADDING", (0, 0), (-1, 6), 4),
                ("BOTTOMPADDING", (0, 0), (-1, 6), 4),
                ("TOPPADDING", (0, 7), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 7), (-1, -1), 6),
                ("SPAN", (0, 8), (0, 10)),
                ("SPAN", (1, 8), (1, 10)),
            ]
        )
    )
    flow.append(sign_table)
    flow.append(Spacer(1, 8))

    flow.append(Paragraph("Observaciones:", st["small"]))
    obs_lines = observaciones.splitlines() if observaciones else ["", "", ""]
    while len(obs_lines) < 3:
        obs_lines.append("")
    for line in obs_lines[:5]:
        flow.append(Paragraph(_esc(line) if line else "……………………………………………………………………………………", st["small"]))
        flow.append(Spacer(1, 2))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=MARGIN_T,
        bottomMargin=MARGIN_B,
        title="Acta de Cierre",
    )
    doc.build(flow)
    filename = _safe_filename(code, description)
    return buf.getvalue(), filename
