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
DEFAULT_HEADER_HEX = "#2474F5"


def _tint_hex(hex_color: str, *, white_mix: float = 0.82) -> colors.Color:
    """Mezcla el color del tenant con blanco para encabezados legibles."""
    raw = str(hex_color or DEFAULT_HEADER_HEX).strip().lstrip("#")
    if len(raw) != 6:
        raw = DEFAULT_HEADER_HEX.lstrip("#")
    try:
        r = int(raw[0:2], 16)
        g = int(raw[2:4], 16)
        b = int(raw[4:6], 16)
    except ValueError:
        r, g, b = 36, 116, 245
    mix = min(max(white_mix, 0.0), 1.0)
    r = int(r + (255 - r) * mix)
    g = int(g + (255 - g) * mix)
    b = int(b + (255 - b) * mix)
    return colors.Color(r / 255.0, g / 255.0, b / 255.0)

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
        "cell": ParagraphStyle(
            "acta_cell",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=9,
            leading=11,
            alignment=TA_LEFT,
            wordWrap="CJK",
        ),
        "cell_bold": ParagraphStyle(
            "acta_cell_bold",
            parent=base["Normal"],
            fontName=FONT_BOLD,
            fontSize=9,
            leading=11,
            alignment=TA_LEFT,
            wordWrap="CJK",
        ),
        "cell_center": ParagraphStyle(
            "acta_cell_center",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=9,
            leading=11,
            alignment=TA_CENTER,
            wordWrap="CJK",
        ),
        "sign_label": ParagraphStyle(
            "acta_sign_label",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=8,
            leading=10,
            alignment=TA_LEFT,
            wordWrap="CJK",
        ),
        "sign_value": ParagraphStyle(
            "acta_sign_value",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=9,
            leading=11,
            alignment=TA_LEFT,
            wordWrap="CJK",
        ),
        "sign_header": ParagraphStyle(
            "acta_sign_header",
            parent=base["Normal"],
            fontName=FONT_BOLD,
            fontSize=9,
            leading=11,
            alignment=TA_CENTER,
        ),
        "sign_footer": ParagraphStyle(
            "acta_sign_footer",
            parent=base["Normal"],
            fontName=FONT,
            fontSize=8,
            leading=10,
            alignment=TA_CENTER,
        ),
    }


def generate_acta_cierre_pdf(payload: dict[str, Any]) -> tuple[bytes, str]:
    """Genera bytes PDF y nombre de archivo a partir de datos ya resueltos."""
    st = _styles()
    header_bg = _tint_hex(str(payload.get("primary_hex") or DEFAULT_HEADER_HEX))
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
            [
                Paragraph("Macroregión", st["cell_bold"]),
                Paragraph("Departamento", st["cell_bold"]),
                Paragraph("Provincia", st["cell_bold"]),
                Paragraph("Distrito", st["cell_bold"]),
            ],
            [
                Paragraph(_esc(macro), st["cell_center"]),
                Paragraph(_esc(dept), st["cell_center"]),
                Paragraph(_esc(prov), st["cell_center"]),
                Paragraph(_esc(dist), st["cell_center"]),
            ],
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
                ("BACKGROUND", (0, 0), (-1, 0), header_bg),
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
        [
            Paragraph("Conceptos", st["cell_bold"]),
            Paragraph("Cantidad", st["cell_bold"]),
            Paragraph("Observaciones", st["cell_bold"]),
        ],
        [
            Paragraph("Total bienes registrados en BD del Banco de la Nación (Margesi)", st["cell"]),
            Paragraph(str(total_bd), st["cell_center"]),
            Paragraph("", st["cell"]),
        ],
        [
            Paragraph("Bienes Conforme (Margesi conciliados)", st["cell"]),
            Paragraph(str(conforme), st["cell_center"]),
            Paragraph("Bienes registrados en la base de datos de la sede ubicados", st["cell"]),
        ],
        [
            Paragraph("Bienes Faltantes (Margesi faltantes)", st["cell"]),
            Paragraph(str(faltantes), st["cell_center"]),
            Paragraph("Bienes registrados en la base de datos de la sede no ubicados.", st["cell"]),
        ],
        [
            Paragraph("Bienes Sobrantes (Inventario sobrantes)", st["cell"]),
            Paragraph(str(sobrantes), st["cell_center"]),
            Paragraph("Bienes no registrados en la base de datos de la sede ubicados", st["cell"]),
        ],
        [
            Paragraph("Total de Bienes Inventariados (Conforme + Sobrantes)", st["cell"]),
            Paragraph(str(total_inv), st["cell_center"]),
            Paragraph("", st["cell"]),
        ],
    ]
    # Anchos fijos para forzar wrap (evitar desborde de Observaciones).
    col_conceptos = CONTENT_W * 0.40
    col_cantidad = CONTENT_W * 0.12
    col_obs = CONTENT_W * 0.48
    stats_table = Table(
        stats_rows,
        colWidths=[col_conceptos, col_cantidad, col_obs],
    )
    stats_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("GRID", (0, 0), (-1, -1), BORDER, LINE_COLOR),
                ("BACKGROUND", (0, 0), (-1, 0), header_bg),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
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

    # Firmas: 4 columnas (etiqueta | valor | etiqueta | valor), como el formato físico.
    half = CONTENT_W * 0.5
    label_w = half * 0.32
    value_w = half * 0.68
    dots = "………………………………"

    def _sign_val(raw: str) -> Paragraph:
        text = _esc(raw) if raw.strip() and raw.strip() != "……………………" else dots
        return Paragraph(text, st["sign_value"])

    bn_nombre_p = _sign_val(bn_nombre)
    bn_cargo_p = _sign_val(bn_cargo)
    bn_dni_p = _sign_val(bn_dni)
    sertec_nombre_p = _sign_val(sertec_nombre)
    sertec_cargo_p = _sign_val(sertec_cargo if sertec_cargo.strip() else "Inventariador")
    sertec_dni_p = _sign_val(sertec_dni)

    sign_rows = [
        [
            Paragraph("BANCO DE LA NACION", st["sign_header"]),
            "",
            Paragraph("SERTEC", st["sign_header"]),
            "",
        ],
        [
            Paragraph("Nombre", st["sign_label"]),
            bn_nombre_p,
            Paragraph("Nombre", st["sign_label"]),
            sertec_nombre_p,
        ],
        [
            Paragraph("Cargo", st["sign_label"]),
            bn_cargo_p,
            Paragraph("Cargo", st["sign_label"]),
            sertec_cargo_p,
        ],
        [
            Paragraph("Código/DNI", st["sign_label"]),
            bn_dni_p,
            Paragraph("DNI", st["sign_label"]),
            sertec_dni_p,
        ],
        [
            Paragraph("(Firma y Sello)", st["sign_footer"]),
            "",
            Paragraph("(Firma)", st["sign_footer"]),
            "",
        ],
        ["", "", "", ""],
    ]
    sign_table = Table(
        sign_rows,
        colWidths=[label_w, value_w, label_w, value_w],
        rowHeights=[10 * mm, 9 * mm, 9 * mm, 9 * mm, 8 * mm, 38 * mm],
    )
    sign_table.setStyle(
        TableStyle(
            [
                ("SPAN", (0, 0), (1, 0)),
                ("SPAN", (2, 0), (3, 0)),
                ("SPAN", (0, 4), (1, 4)),
                ("SPAN", (2, 4), (3, 4)),
                ("SPAN", (0, 5), (1, 5)),
                ("SPAN", (2, 5), (3, 5)),
                ("BACKGROUND", (0, 0), (1, 0), header_bg),
                ("BACKGROUND", (2, 0), (3, 0), header_bg),
                ("GRID", (0, 0), (-1, -1), BORDER, LINE_COLOR),
                ("VALIGN", (0, 0), (-1, 3), "MIDDLE"),
                ("VALIGN", (0, 4), (-1, 4), "MIDDLE"),
                ("VALIGN", (0, 5), (-1, 5), "TOP"),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("ALIGN", (0, 4), (-1, 4), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, 3), 3),
                ("BOTTOMPADDING", (0, 0), (-1, 3), 3),
                ("TOPPADDING", (0, 4), (-1, 5), 4),
                ("BOTTOMPADDING", (0, 4), (-1, 5), 4),
                # Línea vertical fuerte entre BN y SERTEC
                ("LINEBEFORE", (2, 0), (2, -1), 1.25, LINE_COLOR),
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
