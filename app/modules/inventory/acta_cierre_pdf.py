"""PDF «Anexo 005 – Acta de Cierre» para Reporte Locales."""

from __future__ import annotations

import io
import re
from datetime import date, datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PAGE_W, PAGE_H = A4
MARGIN_L = 18 * mm
MARGIN_R = 18 * mm
MARGIN_T = 14 * mm
MARGIN_B = 15 * mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R

FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
BORDER = 0.6
LINE_COLOR = colors.HexColor("#B8BEC6")
TEXT_COLOR = colors.HexColor("#1F2328")
MUTED_COLOR = colors.HexColor("#6B7280")
ZEBRA_BG = colors.HexColor("#F7F8FA")
DEFAULT_HEADER_HEX = "#2474F5"
EMPTY = "……………………"


def _rgb(hex_color: str) -> tuple[int, int, int]:
    raw = str(hex_color or DEFAULT_HEADER_HEX).strip().lstrip("#")
    if len(raw) != 6:
        raw = DEFAULT_HEADER_HEX.lstrip("#")
    try:
        return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16)
    except ValueError:
        return 36, 116, 245


def _solid_hex(hex_color: str) -> colors.Color:
    r, g, b = _rgb(hex_color)
    return colors.Color(r / 255.0, g / 255.0, b / 255.0)


def _tint_hex(hex_color: str, *, white_mix: float = 0.82) -> colors.Color:
    """Mezcla el color del tenant con blanco (fondos suaves)."""
    r, g, b = _rgb(hex_color)
    mix = min(max(white_mix, 0.0), 1.0)
    r = int(r + (255 - r) * mix)
    g = int(g + (255 - g) * mix)
    b = int(b + (255 - b) * mix)
    return colors.Color(r / 255.0, g / 255.0, b / 255.0)


def _text_on(hex_color: str) -> colors.Color:
    """Blanco o texto oscuro según la luminancia del color de fondo."""
    r, g, b = _rgb(hex_color)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    return colors.white if luminance < 0.62 else TEXT_COLOR


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
        return EMPTY
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


def _styles(header_fg: colors.Color, accent: colors.Color) -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()["Normal"]

    def ps(name: str, **kw: Any) -> ParagraphStyle:
        kw.setdefault("fontName", FONT)
        kw.setdefault("textColor", TEXT_COLOR)
        return ParagraphStyle(f"acta_{name}", parent=base, **kw)

    return {
        "kicker": ps("kicker", fontName=FONT_BOLD, fontSize=10, leading=13, alignment=TA_CENTER),
        "title": ps("title", fontName=FONT_BOLD, fontSize=15, leading=18, alignment=TA_CENTER, textColor=accent),
        "sede": ps("sede", fontName=FONT_BOLD, fontSize=10, leading=12, alignment=TA_CENTER),
        "body": ps("body", fontSize=10, leading=14, alignment=TA_JUSTIFY, spaceAfter=6),
        "small": ps("small", fontSize=9, leading=12),
        "th": ps("th", fontName=FONT_BOLD, fontSize=9, leading=11, textColor=header_fg),
        "th_center": ps("th_center", fontName=FONT_BOLD, fontSize=9, leading=11, textColor=header_fg, alignment=TA_CENTER),
        "cell": ps("cell", fontSize=9, leading=11.5, wordWrap="CJK"),
        "cell_bold": ps("cell_bold", fontName=FONT_BOLD, fontSize=9, leading=11.5, wordWrap="CJK"),
        "cell_center": ps("cell_center", fontSize=9, leading=11.5, alignment=TA_CENTER, wordWrap="CJK"),
        "cell_obs": ps("cell_obs", fontSize=8.5, leading=11, textColor=MUTED_COLOR, wordWrap="CJK"),
        "qty": ps("qty", fontName=FONT_BOLD, fontSize=10, leading=12, alignment=TA_CENTER),
        "sign_label": ps("sign_label", fontSize=8, leading=10, textColor=MUTED_COLOR),
        "sign_value": ps("sign_value", fontSize=9, leading=11, wordWrap="CJK"),
        "sign_footer": ps("sign_footer", fontSize=8, leading=10, alignment=TA_CENTER, textColor=MUTED_COLOR),
    }


def _header_table_style(header_bg: colors.Color, *, header_rows: int = 1) -> list[tuple]:
    last = header_rows - 1
    return [
        ("BACKGROUND", (0, 0), (-1, last), header_bg),
        ("BOX", (0, 0), (-1, -1), BORDER, LINE_COLOR),
        ("INNERGRID", (0, 0), (-1, -1), BORDER, LINE_COLOR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]


def generate_acta_cierre_pdf(payload: dict[str, Any]) -> tuple[bytes, str]:
    """Genera bytes PDF y nombre de archivo a partir de datos ya resueltos."""
    primary_hex = str(payload.get("primary_hex") or DEFAULT_HEADER_HEX)
    header_bg = _solid_hex(primary_hex)
    header_fg = _text_on(primary_hex)
    soft_bg = _tint_hex(primary_hex, white_mix=0.9)
    # El título usa el color del tenant solo si contrasta sobre blanco.
    st = _styles(header_fg, header_bg if header_fg == colors.white else TEXT_COLOR)

    code = _cell(payload.get("establishment_code"))
    description = _cell(payload.get("establishment_description"))
    day, month, year = _format_acta_date(payload.get("fecha"))
    hora = _cell(payload.get("hora"), empty="……")
    macro = _cell(payload.get("macroregion"))
    dept = _cell(payload.get("departamento"))
    prov = _cell(payload.get("provincia"))
    dist = _cell(payload.get("distrito"))
    oficina = _cell(payload.get("oficina_sede"), empty=description or EMPTY)
    reps_banco = _cell(payload.get("representantes_banco"))
    rep_sertec = _cell(payload.get("representante_sertec"))
    sede_label = f"{code} - {description}".strip(" -") if description else code

    total_bd = int(payload.get("total_bd") or 0)
    conforme = int(payload.get("conforme") or 0)
    faltantes = int(payload.get("faltantes") or 0)
    sobrantes = int(payload.get("sobrantes") or 0)
    total_inv = conforme + sobrantes

    bn_nombre = _cell(payload.get("bn_nombre"))
    bn_cargo = _cell(payload.get("bn_cargo"))
    bn_dni = _cell(payload.get("bn_dni"))
    sertec_nombre = _cell(payload.get("sertec_nombre"))
    sertec_cargo = _cell(payload.get("sertec_cargo"), empty="Inventariador")
    sertec_dni = _cell(payload.get("sertec_dni"))
    observaciones = _cell(payload.get("observaciones"))

    # --- Encabezado -------------------------------------------------------
    flow: list[Any] = [
        Paragraph(
            "SERVICIO DE TOMA DE INVENTARIO DE LOS BIENES MUEBLES<br/>"
            "DEL ACTIVO FIJO DEL BANCO DE LA NACION",
            st["kicker"],
        ),
        Spacer(1, 4),
        Paragraph("ACTA DE CIERRE", st["title"]),
        Spacer(1, 6),
    ]

    sede_table = Table(
        [[Paragraph(f"SEDE ( {_esc(code)} ) &nbsp;&nbsp;·&nbsp;&nbsp; {_esc(description or sede_label)}", st["sede"])]],
        colWidths=[CONTENT_W],
    )
    sede_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), soft_bg),
                ("LINEABOVE", (0, 0), (-1, 0), 1.6, header_bg),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    flow.append(sede_table)
    flow.append(Spacer(1, 6))

    geo_table = Table(
        [
            [Paragraph(h, st["th_center"]) for h in ("Macroregión", "Departamento", "Provincia", "Distrito")],
            [Paragraph(_esc(v), st["cell_center"]) for v in (macro, dept, prov, dist)],
        ],
        colWidths=[CONTENT_W * 0.25] * 4,
    )
    geo_table.setStyle(TableStyle(_header_table_style(header_bg)))
    flow.append(geo_table)
    flow.append(Spacer(1, 8))

    # --- Cuerpo -----------------------------------------------------------
    flow.append(
        Paragraph(
            (
                f"Siendo las <b>{_esc(hora)}</b> horas del día <b>{_esc(day)} de {_esc(month)} del {year}</b>, "
                f"en la Oficina de la Sede <b>{_esc(oficina)}</b>, se reunieron los señores "
                f"{_esc(reps_banco)}, en representación del BANCO DE LA NACION y de la otra parte "
                f"el Sr (srta) {_esc(rep_sertec)} en representación de la Empresa SERTEC Soluciones "
                f"Empresariales SAC, con el objeto de suscribir el Acta de Cierre del Inventario "
                f"Físico de Bienes Muebles de la Sede <b>{_esc(sede_label)}</b>."
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
            Paragraph("Conceptos", st["th"]),
            Paragraph("Cantidad", st["th_center"]),
            Paragraph("Observaciones", st["th"]),
        ],
        [
            Paragraph("Total bienes registrados en BD del Banco de la Nación (Margesi)", st["cell"]),
            Paragraph(f"{total_bd:,}", st["qty"]),
            Paragraph("", st["cell_obs"]),
        ],
        [
            Paragraph("Bienes Conforme (Inventario conciliados)", st["cell"]),
            Paragraph(f"{conforme:,}", st["qty"]),
            Paragraph("Bienes registrados en la base de datos de la sede ubicados.", st["cell_obs"]),
        ],
        [
            Paragraph("Bienes Faltantes (Margesi faltantes)", st["cell"]),
            Paragraph(f"{faltantes:,}", st["qty"]),
            Paragraph("Bienes registrados en la base de datos de la sede no ubicados.", st["cell_obs"]),
        ],
        [
            Paragraph("Bienes Sobrantes (Inventario sobrantes)", st["cell"]),
            Paragraph(f"{sobrantes:,}", st["qty"]),
            Paragraph("Bienes no registrados en la base de datos de la sede ubicados.", st["cell_obs"]),
        ],
        [
            Paragraph("Total de Bienes Inventariados (Conforme + Sobrantes)", st["cell_bold"]),
            Paragraph(f"{total_inv:,}", st["qty"]),
            Paragraph("", st["cell_obs"]),
        ],
    ]
    stats_table = Table(stats_rows, colWidths=[CONTENT_W * 0.42, CONTENT_W * 0.13, CONTENT_W * 0.45])
    stats_table.setStyle(
        TableStyle(
            _header_table_style(header_bg)
            + [
                ("BACKGROUND", (0, 2), (-1, 2), ZEBRA_BG),
                ("BACKGROUND", (0, 4), (-1, 4), ZEBRA_BG),
                ("BACKGROUND", (0, -1), (-1, -1), soft_bg),
                ("LINEABOVE", (0, -1), (-1, -1), 1.2, header_bg),
                ("TOPPADDING", (0, 1), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
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
    flow.append(Paragraph("Los bienes Faltantes serán conciliados o buscados a nivel nacional.", st["body"]))
    flow.append(Spacer(1, 2))

    # --- Firmas: etiqueta | valor | etiqueta | valor ----------------------
    half = CONTENT_W * 0.5
    label_w = half * 0.3
    value_w = half * 0.7

    def _sign_val(raw: str) -> Paragraph:
        return Paragraph(_esc(raw), st["sign_value"])

    sign_rows = [
        [Paragraph("BANCO DE LA NACION", st["th_center"]), "", Paragraph("SERTEC", st["th_center"]), ""],
        [Paragraph("Nombre", st["sign_label"]), _sign_val(bn_nombre), Paragraph("Nombre", st["sign_label"]), _sign_val(sertec_nombre)],
        [Paragraph("Cargo", st["sign_label"]), _sign_val(bn_cargo), Paragraph("Cargo", st["sign_label"]), _sign_val(sertec_cargo)],
        [Paragraph("Código/DNI", st["sign_label"]), _sign_val(bn_dni), Paragraph("DNI", st["sign_label"]), _sign_val(sertec_dni)],
        ["", "", "", ""],
        [Paragraph("(Firma y Sello)", st["sign_footer"]), "", Paragraph("(Firma)", st["sign_footer"]), ""],
    ]
    sign_table = Table(
        sign_rows,
        colWidths=[label_w, value_w, label_w, value_w],
        rowHeights=[7 * mm, 7 * mm, 7 * mm, 7 * mm, 22 * mm, 6 * mm],
    )
    sign_table.setStyle(
        TableStyle(
            _header_table_style(header_bg)
            + [
                ("SPAN", (0, 0), (1, 0)),
                ("SPAN", (2, 0), (3, 0)),
                ("SPAN", (0, 4), (1, 4)),
                ("SPAN", (2, 4), (3, 4)),
                ("SPAN", (0, 5), (1, 5)),
                ("SPAN", (2, 5), (3, 5)),
                ("BACKGROUND", (0, 1), (0, 3), ZEBRA_BG),
                ("BACKGROUND", (2, 1), (2, 3), ZEBRA_BG),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                # Línea de firma sobre la leyenda.
                ("LINEABOVE", (0, 5), (1, 5), 0.9, TEXT_COLOR),
                ("LINEABOVE", (2, 5), (3, 5), 0.9, TEXT_COLOR),
                ("LINEBEFORE", (2, 0), (2, -1), 1.2, header_bg),
            ]
        )
    )

    obs_lines = [ln for ln in observaciones.splitlines()] if observaciones else []
    obs_body: Any
    if obs_lines:
        obs_body = Paragraph("<br/>".join(_esc(ln) if ln.strip() else "" for ln in obs_lines), st["small"])
    else:
        obs_body = Paragraph(
            "<br/><br/>".join(["……………………………………………………………………………………………………………………………"] * 2),
            st["small"],
        )
    obs_table = Table(
        [[Paragraph("Observaciones", st["th"])], [obs_body]],
        colWidths=[CONTENT_W],
    )
    obs_table.setStyle(
        TableStyle(
            _header_table_style(header_bg)
            + [
                ("TOPPADDING", (0, 1), (-1, 1), 6),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
            ]
        )
    )

    flow.append(KeepTogether([sign_table, Spacer(1, 8), obs_table]))

    generated_at = datetime.now().strftime("%d/%m/%Y %H:%M")

    def _on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        # Franja superior con el color del tenant.
        canvas.setFillColor(header_bg)
        canvas.rect(0, PAGE_H - 5 * mm, PAGE_W, 5 * mm, stroke=0, fill=1)
        # Pie: línea + leyenda.
        y = MARGIN_B - 7 * mm
        canvas.setStrokeColor(LINE_COLOR)
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN_L, y + 4 * mm, PAGE_W - MARGIN_R, y + 4 * mm)
        canvas.setFont(FONT, 7.5)
        canvas.setFillColor(MUTED_COLOR)
        canvas.drawString(MARGIN_L, y, f"Acta de Cierre · Sede {sede_label}")
        canvas.drawRightString(PAGE_W - MARGIN_R, y, f"Generado el {generated_at} · Página {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=MARGIN_T,
        bottomMargin=MARGIN_B,
        title=f"Acta de Cierre - {sede_label}",
    )
    doc.build(flow, onFirstPage=_on_page, onLaterPages=_on_page)
    filename = _safe_filename(code, description)
    return buf.getvalue(), filename
