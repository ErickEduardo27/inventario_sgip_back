"""PDF «Anexo 002 – Ficha de Levantamiento de Inventario» (diseño alineado a plantilla BN)."""

from __future__ import annotations

import io
import re
from datetime import date
from typing import Any
from uuid import UUID

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.tenant_logo_storage import read_tenant_logo_bytes
from app.core.inventory_numbers import format_hoj_num

from app.modules.iam.models import User
from app.modules.inventory import models as m
from app.modules.inventory.geo_models import InvDepartment
from app.modules.settings.models import WorkspaceSettings

PAGE_W, PAGE_H = landscape(A4)
MARGIN_L = 10 * mm
MARGIN_R = 10 * mm
MARGIN_T = 8 * mm
MARGIN_B = 8 * mm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R

# Anchos columnas ítems (suma ≈ CONTENT_W)
COL_ITEM = 7 * mm
COL_INV = 11 * mm
COL_CINT = 20 * mm
COL_SBN = 26 * mm
COL_DESC = 74 * mm
COL_EST = 6 * mm
COL_USO = 8 * mm
COL_COL = 12 * mm
COL_MAR = 14 * mm
COL_MOD = 14 * mm
COL_SER = 32 * mm
COL_MED = 14 * mm
COL_OBS = 44 * mm
# Aprox. caracteres que caben en una línea de la columna Descripción (74 mm, 6 pt)
DESC_MAX_CHARS = 52
ITEM_COL_WIDTHS = [
    COL_ITEM,
    COL_INV,
    COL_CINT,
    COL_SBN,
    COL_DESC,
    COL_EST,
    COL_USO,
    COL_COL,
    COL_MAR,
    COL_MOD,
    COL_SER,
    COL_MED,
    COL_OBS,
]

BORDER = 0.5
LINE_COLOR = colors.HexColor("#999999")
FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

LOGO_MAX_W = 40 * mm
LOGO_MAX_H = 22 * mm

FOOTER_BLOCK_H = 26 * mm  # reserva mínima; la altura real se mide al generar
FOOTER_NOTES_GAP = 1.5 * mm
HEADER_TABLE_GAP = 0.5 * mm


def _cell(value: object, *, empty_label: str = "") -> str:
    s = str(value or "").strip()
    return s if s else empty_label


def _display(value: object, *, empty_label: str = "") -> str:
    s = _cell(value, empty_label=empty_label)
    return s.upper() if s else s


def _extra(row: m.InvItemCard) -> dict[str, Any]:
    ex = row.extra
    return ex if isinstance(ex, dict) else {}


def _person_doc_name(number: object, name: object, *, upper_name: bool = True) -> str:
    num = _cell(number)
    nom = _cell(name)
    if upper_name and nom:
        nom = nom.upper()
    if num and nom:
        return f"({num}) {nom}"
    return (nom or num or "").upper() if upper_name else (nom or num or "")


def _resolve_user_label(db: Session, tenant_id: UUID, user_id: UUID | None) -> str:
    if not user_id:
        return ""
    user = db.get(User, user_id)
    if not user or user.tenant_id != tenant_id:
        return ""
    person = db.scalar(
        select(m.InvPerson)
        .where(
            m.InvPerson.tenant_id == tenant_id,
            or_(
                m.InvPerson.name == user.full_name,
                m.InvPerson.email.isnot(None) & (m.InvPerson.email.ilike(user.email)),
            ),
        )
        .limit(1)
    )
    if person:
        name = person.name or user.full_name
        return _person_doc_name(person.number, name)
    return (user.full_name or "").upper()


def _format_fecha(value: date | None) -> str:
    if not value:
        return ""
    return value.strftime("%d-%m-%Y")


def _item_field(ex: dict[str, Any], key: str, *, default: str = "") -> str:
    v = _cell(ex.get(key), empty_label=default)
    return v or default


def _display_field(ex: dict[str, Any], key: str, *, default: str = "") -> str:
    return _display(_item_field(ex, key, default=default), empty_label=default.upper() if default else "")


def _code_desc(code: object, desc: object, *, paren_code: bool = True) -> str:
    co = _display(code)
    de = _display(desc)
    if co and de:
        return f"({co}) {de}" if paren_code else f"{co} {de}"
    return de or co or ""


def _code_dash_desc(code: object, desc: object) -> str:
    co = _display(code)
    de = _display(desc)
    if co and de:
        return f"({co}) – {de}"
    return de or (f"({co})" if co else "")


def _styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle(
            "AnexoTitle",
            fontName=FONT_BOLD,
            fontSize=12,
            leading=14,
            alignment=TA_CENTER,
            spaceAfter=2,
        ),
        "hdr": ParagraphStyle(
            "AnexoHdr",
            fontName=FONT,
            fontSize=8,
            leading=10,
            alignment=TA_LEFT,
        ),
        "hdr_right": ParagraphStyle(
            "AnexoHdrRight",
            fontName=FONT,
            fontSize=7,
            leading=8.5,
            alignment=TA_RIGHT,
        ),
        "cell": ParagraphStyle(
            "AnexoCell",
            fontName=FONT,
            fontSize=6,
            leading=7,
            alignment=TA_LEFT,
        ),
        "cell_center": ParagraphStyle(
            "AnexoCellCenter",
            fontName=FONT,
            fontSize=6,
            leading=7,
            alignment=TA_CENTER,
        ),
        "cell_header": ParagraphStyle(
            "AnexoCellHeader",
            fontName=FONT_BOLD,
            fontSize=6,
            leading=7,
            alignment=TA_CENTER,
        ),
        "cell_ser": ParagraphStyle(
            "AnexoCellSer",
            fontName=FONT,
            fontSize=5,
            leading=5.5,
            alignment=TA_CENTER,
        ),
        "cell_desc": ParagraphStyle(
            "AnexoCellDesc",
            fontName=FONT,
            fontSize=6,
            leading=7,
            alignment=TA_LEFT,
            wordWrap=None,
        ),
        "footer": ParagraphStyle(
            "AnexoFooter",
            fontName=FONT,
            fontSize=6,
            leading=7,
            alignment=TA_LEFT,
        ),
        "sign": ParagraphStyle(
            "AnexoSign",
            fontName=FONT,
            fontSize=7,
            leading=7.5,
            alignment=TA_CENTER,
            spaceBefore=0,
            spaceAfter=0,
        ),
    }


def _table_grid() -> TableStyle:
    return TableStyle(
        [
            ("FONTNAME", (0, 0), (-1, -1), FONT),
            ("FONTSIZE", (0, 0), (-1, -1), 6),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 1),
            ("RIGHTPADDING", (0, 0), (-2, -1), 3),
            ("RIGHTPADDING", (-1, 0), (-1, -1), 1),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
            ("LINEBELOW", (0, 0), (-1, 0), BORDER, LINE_COLOR),
            ("FONTNAME", (0, 0), (-1, 0), FONT_BOLD),
        ]
    )


def _hdr_field(label: str, value: object) -> str:
    v = _display(value).replace("&", "&amp;")
    label_u = label.upper()
    return f"<b>{label_u}:</b> {v}"


def _hdr_column(fields: list[tuple[str, object]], st: ParagraphStyle) -> Paragraph:
    lines = [_hdr_field(label, value) for label, value in fields]
    return Paragraph("<br/>".join(lines), st)


def _scale_col_widths(widths: list[float], total_w: float) -> list[float]:
    current = sum(widths)
    if current <= 0:
        return widths
    factor = total_w / current
    return [w * factor for w in widths]


def _measure_flowables_height(flowables: list[Any], width: float) -> float:
    total = 0.0
    for flow in flowables:
        _, h = flow.wrap(width, PAGE_H)
        total += h
    return total


def _measure_table_height(table: Table, width: float) -> float:
    _, h = table.wrap(width, PAGE_H)
    return max(h, FOOTER_BLOCK_H)


def _measure_paragraph_height(para: Paragraph, width: float) -> float:
    _, h = para.wrap(width, PAGE_H)
    return h


def _build_item_count_note(item_count: int, st: dict[str, ParagraphStyle]) -> list[Any]:
    return [
        Spacer(1, FOOTER_NOTES_GAP),
        Paragraph(f"CANTIDAD DE BIENES POR HOJA: {item_count}", st["footer"]),
    ]


def _resolve_logo_bytes(db: Session, tenant_id: UUID) -> bytes | None:
    row = db.scalar(select(WorkspaceSettings).where(WorkspaceSettings.tenant_id == tenant_id))
    if not row or not row.logo_url:
        return None
    return read_tenant_logo_bytes(row.logo_url, tenant_id)


def _load_logo_image(logo_bytes: bytes | None) -> Image | None:
    if not logo_bytes:
        return None
    try:
        img = Image(io.BytesIO(logo_bytes))
        iw, ih = float(img.imageWidth), float(img.imageHeight)
        if iw <= 0 or ih <= 0:
            return None
        scale = min(LOGO_MAX_W / iw, LOGO_MAX_H / ih)
        img.drawWidth = iw * scale
        img.drawHeight = ih * scale
        img.hAlign = "LEFT"
        return img
    except Exception:
        return None


def _build_title_banner(
    inv_year: int, st: dict[str, ParagraphStyle], content_w: float, logo_bytes: bytes | None
) -> Table:
    title = Paragraph(f"FICHA DE LEVANTAMIENTO DE INVENTARIO {inv_year}", st["title"])
    logo = _load_logo_image(logo_bytes)
    if logo:
        side_w = logo.drawWidth + 4 * mm
        center_w = max(content_w - 2 * side_w, content_w * 0.5)
        side_w = (content_w - center_w) / 2
        tbl = Table([[logo, title, ""]], colWidths=[side_w, center_w, side_w], hAlign="LEFT")
        tbl.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN", (1, 0), (1, 0), "CENTER"),
                    ("LEFTPADDING", (0, 0), (0, 0), 0),
                    ("RIGHTPADDING", (0, 0), (0, 0), 2),
                    ("LEFTPADDING", (1, 0), (1, 0), 0),
                    ("RIGHTPADDING", (1, 0), (1, 0), 0),
                    ("LEFTPADDING", (2, 0), (2, 0), 0),
                    ("RIGHTPADDING", (2, 0), (2, 0), 0),
                    ("TOPPADDING", (0, 0), (-1, -1), 0),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        return tbl

    tbl = Table([[title]], colWidths=[content_w], hAlign="LEFT")
    tbl.setStyle(
        TableStyle(
            [
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return tbl


def _build_header_fields_table(
    *,
    resp_label: str,
    dept_name: str,
    fecha: str,
    gerencia: str,
    sede: str,
    hoj_num: str,
    area: str,
    piso: str,
    nota: str,
    ambiente: str,
    inventariador: str,
    digitador: str,
    st: dict[str, ParagraphStyle],
    content_w: float = CONTENT_W,
) -> Table:
    col1_w = content_w * 0.40
    col2_w = content_w * 0.38
    col3_w = content_w - col1_w - col2_w

    col1 = _hdr_column(
        [
            ("Usuario responsable", resp_label),
            ("Gerencia", gerencia),
            ("Área orgánica", area),
            ("Nota", nota),
            ("Inventariador", inventariador),
        ],
        st["hdr"],
    )
    col2 = _hdr_column(
        [
            ("Departamento", dept_name),
            ("Sede", sede),
            ("Piso", piso),
            ("Ambiente", ambiente),
            ("Digitador", digitador),
        ],
        st["hdr"],
    )
    col3 = _hdr_column(
        [
            ("Fecha", fecha),
            ("Hoja N°", hoj_num),
        ],
        st["hdr_right"],
    )

    tbl = Table(
        [[col1, col2, col3]],
        colWidths=[col1_w, col2_w, col3_w],
        hAlign="LEFT",
    )
    tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LEFTPADDING", (0, 0), (0, 0), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 4),
                ("LEFTPADDING", (1, 0), (1, 0), 4),
                ("RIGHTPADDING", (1, 0), (1, 0), 4),
                ("LEFTPADDING", (2, 0), (2, 0), 8),
                ("RIGHTPADDING", (2, 0), (2, 0), 0),
                ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                ("LINEBELOW", (0, 0), (2, 0), BORDER, LINE_COLOR),
            ]
        )
    )
    return tbl


def _build_header_section(
    *,
    inv_year: int,
    resp_label: str,
    dept_name: str,
    fecha: str,
    gerencia: str,
    sede: str,
    hoj_num: str,
    area: str,
    piso: str,
    nota: str,
    ambiente: str,
    inventariador: str,
    digitador: str,
    st: dict[str, ParagraphStyle],
    content_w: float = CONTENT_W,
    logo_bytes: bytes | None = None,
) -> list[Any]:
    return [
        _build_title_banner(inv_year, st, content_w, logo_bytes),
        Spacer(1, HEADER_TABLE_GAP),
        _build_header_fields_table(
            resp_label=resp_label,
            dept_name=dept_name,
            fecha=fecha,
            gerencia=gerencia,
            sede=sede,
            hoj_num=hoj_num,
            area=area,
            piso=piso,
            nota=nota,
            ambiente=ambiente,
            inventariador=inventariador,
            digitador=digitador,
            st=st,
            content_w=content_w,
        ),
    ]


def _items_table_style() -> TableStyle:
    style = _table_grid()
    style.add("ALIGN", (0, 1), (3, -1), "CENTER")
    style.add("ALIGN", (5, 1), (6, -1), "CENTER")
    return style


def _serie_cell(ex: dict[str, Any], st: dict[str, ParagraphStyle]) -> Paragraph:
    raw = _display_field(ex, "mar_ser", default="S/SERIE")
    text = _escape_paragraph(raw)
    return Paragraph(text, st["cell_ser"])


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _truncate_chars(value: str, max_len: int) -> str:
    if len(value) <= max_len:
        return value
    return value[: max_len - 3].rstrip() + "..."


def _escape_paragraph(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _item_description(it: m.InvItemCard, ex: dict[str, Any], *, max_len: int = DESC_MAX_CHARS) -> str:
    parts = [_cell(it.mar_des), _item_field(ex, "mar_esp")]
    combined = _collapse_whitespace(" ".join(p for p in parts if p))
    if not combined:
        return ""
    return _truncate_chars(combined.upper(), max_len)


def _item_row(idx: int, it: m.InvItemCard, st: dict[str, ParagraphStyle]) -> list[Any]:
    ex = _extra(it)
    desc = _escape_paragraph(_item_description(it, ex))

    def _p(value: object, style: str, *, default: str = "") -> Paragraph:
        return Paragraph(_escape_paragraph(_display(value, empty_label=default)), st[style])

    def _pf(key: str, style: str, *, default: str = "") -> Paragraph:
        return Paragraph(_escape_paragraph(_display_field(ex, key, default=default)), st[style])

    return [
        Paragraph(str(idx), st["cell_center"]),
        _p(it.inv_num, "cell_center"),
        _p(it.mar_num, "cell_center"),
        _p(it.inv_num_2, "cell_center"),
        Paragraph(desc, st["cell_desc"]),
        _pf("mar_est", "cell_center"),
        _pf("mar_uso", "cell_center"),
        _pf("mar_col", "cell"),
        _pf("mar_mar", "cell", default="S/MARCA"),
        _pf("mar_mod", "cell", default="S/MODELO"),
        _serie_cell(ex, st),
        _pf("mar_med", "cell", default="S/MEDIDA"),
        _pf("mar_obs", "cell"),
    ]


def _items_header_row(inv_year: int, st: dict[str, ParagraphStyle]) -> list[Any]:
    inv_col = f"I.{inv_year}"
    return [
        Paragraph("ITEM", st["cell_header"]),
        Paragraph(inv_col, st["cell_header"]),
        Paragraph("C.INTERNO", st["cell_header"]),
        Paragraph("SBN", st["cell_header"]),
        Paragraph("DESCRIPCIÓN", st["cell_header"]),
        Paragraph("EST", st["cell_header"]),
        Paragraph("USO", st["cell_header"]),
        Paragraph("COLOR", st["cell_header"]),
        Paragraph("MARCA", st["cell_header"]),
        Paragraph("MODELO", st["cell_header"]),
        Paragraph("SERIE", st["cell_header"]),
        Paragraph("MEDIDAS", st["cell_header"]),
        Paragraph("OBS.", st["cell_header"]),
    ]


def _build_items_table(
    items: list[m.InvItemCard], inv_year: int, st: dict[str, ParagraphStyle], content_w: float = CONTENT_W
) -> Table:
    col_widths = _scale_col_widths(ITEM_COL_WIDTHS, content_w)
    rows: list[list[Any]] = [_items_header_row(inv_year, st)]
    rows.extend(_item_row(idx, it, st) for idx, it in enumerate(items, start=1))

    tbl = Table(
        rows,
        colWidths=col_widths,
        repeatRows=1,
        splitByRow=1,
        splitInRow=1,
        hAlign="LEFT",
    )
    tbl.setStyle(_items_table_style())
    return tbl


def _build_signatures_table(st: dict[str, ParagraphStyle], content_w: float = CONTENT_W) -> Table:
    sign_line_w = 48 * mm
    sign_gap = max(4 * mm, (content_w - 3 * sign_line_w) / 2)
    col_w = [sign_line_w, sign_gap, sign_line_w, sign_gap, sign_line_w]

    def _sign_cell(line1: str, line2: str) -> Paragraph:
        t1 = _escape_paragraph(line1.upper())
        t2 = _escape_paragraph(line2.upper())
        return Paragraph(f"{t1}<br/>{t2}", st["sign"])

    empty = ""
    tbl = Table(
        [
            [empty, empty, empty, empty, empty],
            [
                _sign_cell("Firma del Usuario Responsable", "Banco de la Nación"),
                empty,
                _sign_cell("Firma del Inventariador", "SERTEC"),
                empty,
                _sign_cell("Vº Bº Supervisor de Inventario", "SERTEC"),
            ],
        ],
        colWidths=col_w,
        hAlign="CENTER",
    )
    tbl.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), FONT),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LINEBELOW", (0, 0), (0, 0), BORDER, colors.black),
                ("LINEBELOW", (2, 0), (2, 0), BORDER, colors.black),
                ("LINEBELOW", (4, 0), (4, 0), BORDER, colors.black),
                ("TOPPADDING", (0, 0), (-1, 0), 16),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                ("TOPPADDING", (0, 1), (-1, 1), 3),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 0),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]
        )
    )
    return tbl


def _draw_page_header_footer(
    canvas: Any,
    doc: SimpleDocTemplate,
    *,
    header_flowables: list[Any],
    legend_para: Paragraph,
    legend_h: float,
    footer_table: Table,
    footer_h: float,
) -> None:
    canvas.saveState()
    width = doc.width
    left = doc.leftMargin
    y = doc.pagesize[1] - MARGIN_T

    for flow in header_flowables:
        _, h = flow.wrap(width, PAGE_H)
        y -= h
        flow.drawOn(canvas, left, y)

    footer_y = MARGIN_B
    legend_y = footer_y + footer_h + FOOTER_NOTES_GAP
    legend_para.wrap(width, legend_h)
    legend_para.drawOn(canvas, left, legend_y)

    footer_table.wrap(width, footer_h)
    footer_table.drawOn(canvas, left, footer_y)
    canvas.restoreState()


def generate_ficha_pdf(db: Session, tenant_id: UUID, card_id: int) -> tuple[bytes, str]:
    card = db.get(m.InvCard, card_id)
    if not card or card.tenant_id != tenant_id:
        raise ValueError("Hoja no encontrada")

    env = db.get(m.InvEnvironment, card.id_ambiente) if card.id_ambiente else None
    est = db.get(m.InvEstablishment, env.establishment_id) if env and env.establishment_id else None
    cc = db.get(m.InvCostCenter, card.id_ccosto) if card.id_ccosto else None
    resp = db.get(m.InvPerson, card.id_usuario) if card.id_usuario else None

    dept_name = ""
    if est and est.department_id:
        dep = db.get(InvDepartment, est.department_id)
        if dep and dep.description:
            dept_name = _display(dep.description)

    inv_year = card.hoj_fec.year if card.hoj_fec else date.today().year
    hoj_num = format_hoj_num(int(card.hoj_num)) if card.hoj_num is not None else str(card.id).zfill(5)

    items = list(
        db.scalars(
            select(m.InvItemCard)
            .where(m.InvItemCard.tenant_id == tenant_id, m.InvItemCard.id_card == card.id)
            .order_by(m.InvItemCard.id)
        ).all()
    )

    st = _styles()
    resp_label = _person_doc_name(resp.number if resp else None, resp.name if resp else None)
    gerencia = _display(cc.description if cc else None) or _display(est.description if est else None)
    sede = _code_desc(est.code if est else None, est.description if est else None)
    area = _code_dash_desc(cc.code if cc else None, cc.description if cc else None)
    piso = _display(env.floor if env else None)
    nota = _display(card.nota_ficha) or _display(card.nota_interna)
    ambiente = _code_desc(env.code if env else None, env.description if env else None)
    inventariador = _display(_resolve_user_label(db, tenant_id, card.id_inventariador))
    digitador = _display(_resolve_user_label(db, tenant_id, card.id_digitador))
    logo_bytes = _resolve_logo_bytes(db, tenant_id)

    page_w = CONTENT_W
    header_flowables = _build_header_section(
        inv_year=inv_year,
        resp_label=resp_label,
        dept_name=dept_name,
        fecha=_format_fecha(card.hoj_fec),
        gerencia=gerencia,
        sede=sede,
        hoj_num=hoj_num,
        area=area,
        piso=piso,
        nota=nota,
        ambiente=ambiente,
        inventariador=inventariador,
        digitador=digitador,
        st=st,
        content_w=page_w,
        logo_bytes=logo_bytes,
    )
    header_h = _measure_flowables_height(header_flowables, page_w)
    footer_table = _build_signatures_table(st, content_w=page_w)
    footer_h = _measure_table_height(footer_table, page_w)

    legend = (
        "Estado (EST): Bueno: B=, Regular: R, Malo: M, RAEE:X, Chatarra/Inservible: Y | "
        "Medida(metros): L=Largo, A=Ancho, H=Alto / Capacidad / Potencia / Pulgadas / Etc. "
        "Utilización (USO):USO: U, DESUSO: D Nota: 1.El usuario declara haber mostrado todos los bienes "
        "patrimoniales que se encuentran bajo su responsabilidad y no contar con más bienes patrimoniales "
        "materia de inventario. "
        "2. El usuario es responsable de la permanencia y conservación de cada uno de los bienes muebles "
        "descritos, recomendándose tomar las precauciones del caso para evitar sustracciones , deterioros, etc. "
        "3. Cualquier necesidad de traslado del bien mueble dentro o fuera del local del BN, es previamente "
        "comunicado con el personal de Control Patrimonial. "
        "4. En caso de vehículos y maquinaria se adiciona al presente formato el Anexo Nº 04 – Ficha Tecnica de "
        "Vehiculo."
    )
    legend_para = Paragraph(legend.replace("&", "&amp;"), st["footer"])
    legend_h = _measure_paragraph_height(legend_para, page_w)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=MARGIN_L,
        rightMargin=MARGIN_R,
        topMargin=MARGIN_T + header_h,
        bottomMargin=MARGIN_B + footer_h + legend_h + FOOTER_NOTES_GAP * 2,
    )

    def on_page(canvas: Any, doc_: SimpleDocTemplate) -> None:
        _draw_page_header_footer(
            canvas,
            doc_,
            header_flowables=header_flowables,
            legend_para=legend_para,
            legend_h=legend_h,
            footer_table=footer_table,
            footer_h=footer_h,
        )

    story: list[Any] = [
        _build_items_table(items, inv_year, st, content_w=page_w),
        *_build_item_count_note(len(items), st),
    ]

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    filename = (card.pdf or f"HC-{hoj_num}.pdf").strip() or f"HC-{hoj_num}.pdf"
    return buf.getvalue(), filename
