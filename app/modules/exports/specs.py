"""Catálogo de exportaciones del sistema.

Cada exportación declara su permiso, cómo normalizar los filtros (para la clave de deduplicación) y cómo
generar el archivo. Las consultas y los formatos de Excel son los mismos que antes; solo cambia que ahora se
generan en el worker, en streaming a disco y con progreso real.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable
from uuid import UUID

from app.modules.exports import item_photos as _item_photos
from app.modules.inventory.descarga_archivos_service import record_query_export_payload
from app.modules.inventory.schemas import RecordQuery

if TYPE_CHECKING:
    from app.modules.exports.runner import ExportContext

@dataclass(frozen=True)
class StoredOutput:
    """Archivo que el generador ya escribió en el almacenamiento (streaming): el runner no lo vuelve a subir."""

    storage_path: str
    filename: str
    size: int


# Resultado de ``generate``: archivo final en disco y nombre de descarga, o uno ya almacenado.
Generated = tuple[Path, str] | StoredOutput

#: Alcance de datos que entra en la clave. Hoy todas las exportaciones son de todo el tenant (los datos no
#: se filtran por agencia del usuario), así que comparten archivo todos los que tienen permiso de exportar.
#: Si algún módulo empieza a filtrar por alcance, devuelva aquí ese alcance para no mezclar archivos.
TENANT_SCOPE = "tenant"


@dataclass(frozen=True)
class ExportSpec:
    module: str
    label: str
    permission: tuple[str, str]
    formats: tuple[str, ...]
    #: filtros del cliente → (parámetros para generar, parámetros normalizados para la clave)
    parse: Callable[[dict[str, Any]], tuple[dict[str, Any], dict[str, Any]]]
    generate: Callable[["ExportContext", UUID, dict[str, Any], str], Generated]
    scope: Callable[[Any], str] = lambda _user: TENANT_SCOPE
    #: validación con base de datos antes de encolar (errores inmediatos para el usuario)
    precheck: Callable[[Any, UUID, dict[str, Any]], None] | None = None
    #: etiqueta del trabajo para la campanita (p. ej. "Fotos · A01 (parte 2 de 6)"); por defecto ``label``
    describe: Callable[[Any, UUID, dict[str, Any]], str] | None = None
    #: el archivo generado se guarda para siempre y se reutiliza: nunca se regenera desde un pedido normal
    #: (sin ventana de reutilización ni "generar nueva"). Si el objeto desaparece del almacenamiento, sí.
    immutable: bool = False
    #: completa (run, key) con datos persistidos (db, tenant, run, key, crear) → (run, key); p. ej. plan congelado.
    #: Con crear=False (consultas sin efectos) puede lanzar ``NotPlannedError`` si aún no hay nada generado.
    resolve: Callable[[Any, UUID, dict[str, Any], dict[str, Any], bool], tuple[dict[str, Any], dict[str, Any]]] | None = None


class NotPlannedError(LookupError):
    """La exportación todavía no tiene plan congelado (nunca se generó)."""


def _stamp() -> str:
    return date.today().isoformat()


# --- Filtros ----------------------------------------------------------------


def _no_filters(_filters: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    return {}, {}


def _record_query(extra_key: Callable[[RecordQuery], dict[str, Any]] | None = None):
    def parse(filters: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        q = RecordQuery.model_validate(filters or {})
        run = q.model_dump(mode="json")
        key = record_query_export_payload(q, extra=extra_key(q) if extra_key else None)
        return run, key

    return parse


def _margesi_layout(q: RecordQuery) -> dict[str, Any]:
    layout = (q.export_layout or "full").strip().lower()
    return {"export_layout": layout if layout in ("full", "report") else "full"}


def _parse_aptot_locales(filters: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        est_id = int(filters.get("establishment_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Seleccione un local") from exc
    return {"establishment_id": est_id}, {"establishment_id": est_id}


def _parse_reporte_locales(filters: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    ids = sorted({int(x) for x in (filters.get("establishment_ids") or []) if x is not None and str(x).strip()})
    department = (str(filters.get("department_id") or "")).strip() or None
    run = {
        "establishment_ids": ids,
        "department_id": department,
        "include_fotos": bool(filters.get("include_fotos", True)),
        "include_pdfs": bool(filters.get("include_pdfs", True)),
    }
    if not run["include_fotos"] and not run["include_pdfs"]:
        raise ValueError("Elija fotos, PDF o ambos")
    if not ids and not department:
        raise ValueError("Seleccione locales o un departamento")
    return run, dict(run)


def _precheck_reporte_locales(db, tenant_id: UUID, params: dict[str, Any]) -> None:
    from app.modules.inventory import reporte_locales_download_service as rl_dl

    rl_dl.collect_bulk_files(
        db,
        tenant_id,
        establishment_ids=params.get("establishment_ids") or None,
        department_id=params.get("department_id") or None,
        include_fotos=bool(params.get("include_fotos", True)),
        include_pdfs=bool(params.get("include_pdfs", True)),
    )


# --- Generadores ----------------------------------------------------------------


def _master(module: str, sheet_title: str):
    """Maestros (personas, locales, ambientes, centros de costo, catálogo SBN): antes se generaban en la
    petición HTTP; ahora en el worker con la misma consulta y el mismo Excel estilizado."""

    def generate(ctx: "ExportContext", tenant_id: UUID, _params: dict[str, Any], fmt: str) -> Generated:
        from app.modules.inventory.export_queries import get_export_query

        inner_sql, filename_base = get_export_query(module)
        if fmt == "xlsx":
            from app.modules.inventory.excel_styled_export import csv_bytes_to_styled_xlsx_bytes
            from app.modules.tenants.theme import primary_hex_openpyxl

            csv_path = ctx.copy_csv(inner_sql, (str(tenant_id),), bom=False)
            path = ctx.to_xlsx(
                csv_path,
                lambda payload: csv_bytes_to_styled_xlsx_bytes(
                    payload,
                    column_formats={"fecha_creacion": "datetime"},
                    sheet_title=sheet_title[:31],
                    header_color_hex=primary_hex_openpyxl(tenant_id),
                ),
            )
            return path, f"{filename_base}_{_stamp()}.xlsx"
        return ctx.copy_csv(inner_sql, (str(tenant_id),)), f"{filename_base}_{_stamp()}.csv"

    return generate


def _gen_margesi(ctx: "ExportContext", tenant_id: UUID, params: dict[str, Any], fmt: str) -> Generated:
    from app.modules.inventory.csv_export import csv_bytes_to_xlsx_bytes
    from app.modules.inventory.export_queries import build_margesi_export_query

    q = RecordQuery.model_validate(params)
    inner_sql, sql_params, filename_base = build_margesi_export_query(tenant_id, q)
    if fmt == "xlsx":
        csv_path = ctx.copy_csv(inner_sql, sql_params, bom=False)
        return ctx.to_xlsx(csv_path, csv_bytes_to_xlsx_bytes), f"{filename_base}_{_stamp()}.xlsx"
    return ctx.copy_csv(inner_sql, sql_params), f"{filename_base}_{_stamp()}.csv"


def _gen_item_cards(ctx: "ExportContext", tenant_id: UUID, params: dict[str, Any], fmt: str) -> Generated:
    from app.modules.inventory.excel_styled_export import (
        BIENES_INVENTARIADOS_COLUMN_FORMATS,
        csv_bytes_to_styled_xlsx_bytes,
    )
    from app.modules.inventory.export_queries import build_item_cards_export_query
    from app.modules.tenants.theme import primary_hex_openpyxl

    q = RecordQuery.model_validate(params)
    inner_sql, sql_params, filename_base = build_item_cards_export_query(tenant_id, q)
    if fmt == "xlsx":
        csv_path = ctx.copy_csv(inner_sql, sql_params, bom=False)
        path = ctx.to_xlsx(
            csv_path,
            lambda payload: csv_bytes_to_styled_xlsx_bytes(
                payload,
                column_formats=BIENES_INVENTARIADOS_COLUMN_FORMATS,
                sheet_title="Bienes inventariados",
                header_color_hex=primary_hex_openpyxl(tenant_id),
            ),
        )
        return path, f"{filename_base}_{_stamp()}.xlsx"
    return ctx.copy_csv(inner_sql, sql_params), f"{filename_base}_{_stamp()}.csv"


def _gen_hoja_captura(ctx: "ExportContext", tenant_id: UUID, params: dict[str, Any], _fmt: str) -> Generated:
    from app.modules.inventory.excel_styled_export import (
        HOJA_CAPTURA_COLUMN_FORMATS,
        csv_bytes_to_styled_xlsx_bytes,
    )
    from app.modules.inventory.export_queries import build_cards_export_query
    from app.modules.tenants.theme import primary_hex_openpyxl

    q = RecordQuery.model_validate(params)
    inner_sql, sql_params, filename_base = build_cards_export_query(tenant_id, q)
    csv_path = ctx.copy_csv(inner_sql, sql_params, bom=False)
    path = ctx.to_xlsx(
        csv_path,
        lambda payload: csv_bytes_to_styled_xlsx_bytes(
            payload,
            column_formats=HOJA_CAPTURA_COLUMN_FORMATS,
            sheet_title="Hojas de captura",
            header_color_hex=primary_hex_openpyxl(tenant_id),
        ),
    )
    return path, f"{filename_base}_{_stamp()}.xlsx"


def _gen_reporte_aptot(ctx: "ExportContext", tenant_id: UUID, _params: dict[str, Any], fmt: str) -> Generated:
    from app.modules.inventory.export_queries import get_export_query

    inner_sql, _base = get_export_query("reporte_aptot")
    ext = "xlsx" if fmt == "xlsx" else "csv"
    filename = f"reporte_aptot_export_{_stamp()}.{ext}"
    if fmt == "xlsx":
        from app.modules.inventory.excel_styled_export import (
            REPORTE_APTOT_COLUMN_FORMATS,
            csv_bytes_to_styled_xlsx_bytes,
        )
        from app.modules.tenants.theme import primary_hex_openpyxl

        csv_path = ctx.copy_csv(inner_sql, (str(tenant_id),), bom=False, header_spaces=True)
        path = ctx.to_xlsx(
            csv_path,
            lambda payload: csv_bytes_to_styled_xlsx_bytes(
                payload,
                column_formats=REPORTE_APTOT_COLUMN_FORMATS,
                sheet_title="Reporte APTOT",
                header_color_hex=primary_hex_openpyxl(tenant_id),
                zebra_rows=False,
            ),
        )
        return path, filename
    return ctx.copy_csv(inner_sql, (str(tenant_id),), header_spaces=True), filename


def _gen_aptot_locales(ctx: "ExportContext", tenant_id: UUID, params: dict[str, Any], fmt: str) -> Generated:
    from app.db.session import SessionLocal
    from app.modules.inventory import models as m
    from app.modules.inventory.export_queries import build_reporte_aptot_locales_export_query

    est_id = int(params["establishment_id"])
    with SessionLocal() as db:
        est = db.get(m.InvEstablishment, est_id)
        if est is None or est.tenant_id != tenant_id:
            raise ValueError("Local no encontrado")
        code = str(est.code or est_id).strip() or str(est_id)
    inner_sql, sql_params, _base = build_reporte_aptot_locales_export_query(tenant_id, est_id)
    ext = "xlsx" if fmt == "xlsx" else "csv"
    filename = f"reporte_aptot_locales_{est_id}_{code}_{_stamp()}.{ext}"
    if fmt == "xlsx":
        from app.modules.inventory.aptot_locales_excel import csv_bytes_to_aptot_locales_xlsx_bytes

        csv_path = ctx.copy_csv(inner_sql, sql_params, bom=False)
        return ctx.to_xlsx(csv_path, lambda payload: csv_bytes_to_aptot_locales_xlsx_bytes(payload, tenant_id)), filename
    return ctx.copy_csv(inner_sql, sql_params), filename


def _gen_reporte_locales_zip(ctx: "ExportContext", tenant_id: UUID, params: dict[str, Any], _fmt: str) -> Generated:
    import zipfile

    from app.core.reporte_local_storage import read_reporte_local_file_bytes
    from app.db.session import SessionLocal
    from app.modules.inventory import reporte_locales_download_service as rl_dl

    with SessionLocal() as db:
        items = rl_dl.collect_bulk_files(
            db,
            tenant_id,
            establishment_ids=params.get("establishment_ids") or None,
            department_id=params.get("department_id") or None,
            include_fotos=bool(params.get("include_fotos", True)),
            include_pdfs=bool(params.get("include_pdfs", True)),
        )
    total = len(items)
    ids = params.get("establishment_ids") or []
    if params.get("department_id"):
        label = f"dept_{params['department_id']}"
    elif ids:
        label = f"loc_{len(ids)}"
    else:
        label = "seleccion"
    path = ctx.workdir / "reporte_locales.zip"
    written = 0
    # ZIP escrito directo a disco: no se acumulan las fotos en memoria.
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, item in enumerate(items):
            data_mime = read_reporte_local_file_bytes(item.stored_url, tenant_id)
            if data_mime:
                zf.writestr(item.zip_path, data_mime[0])
                written += 1
            ctx.progress(
                5 + int(((idx + 1) / max(total, 1)) * 80),
                f"Empaquetando {idx + 1:,}/{total:,} archivos…".replace(",", "."),
                rows_done=idx + 1,
                rows_total=total,
            )
    if written == 0:
        raise ValueError("Ninguno de los archivos seleccionados está disponible")
    return path, f"reporte_locales_{label}_{_stamp()}.zip"


# --- Registro -------------------------------------------------------------------

SPECS: dict[str, ExportSpec] = {
    s.module: s
    for s in (
        ExportSpec("persons", "Personas", ("personas", "export"), ("csv", "xlsx"), _no_filters, _master("persons", "Personas")),
        ExportSpec("establishments", "Locales", ("locales", "export"), ("csv", "xlsx"), _no_filters, _master("establishments", "Locales")),
        ExportSpec("environments", "Ambientes", ("ambientes", "export"), ("csv", "xlsx"), _no_filters, _master("environments", "Ambientes")),
        ExportSpec("cost_centers", "Centros de costo", ("centro_costo", "export"), ("csv", "xlsx"), _no_filters, _master("cost_centers", "Centros de costo")),
        ExportSpec("list_sbn", "Catálogo SBN", ("list_sbn", "export"), ("csv", "xlsx"), _no_filters, _master("list_sbn", "Catalogo SBN")),
        ExportSpec("margesi", "Margesí", ("margesi", "export"), ("csv", "xlsx"), _record_query(_margesi_layout), _gen_margesi),
        ExportSpec("item_cards", "Bienes inventariados", ("bienes", "export"), ("csv", "xlsx"), _record_query(), _gen_item_cards),
        ExportSpec("hoja_captura", "Hojas de captura", ("hoja_captura", "export"), ("xlsx",), _record_query(), _gen_hoja_captura),
        ExportSpec("reporte_aptot", "Reporte APTOT", ("reporte_aptot", "export"), ("csv", "xlsx"), _no_filters, _gen_reporte_aptot),
        ExportSpec(
            "reporte_aptot_locales",
            "APTOT por local",
            ("reporte_aptot_locales", "export"),
            ("csv", "xlsx"),
            _parse_aptot_locales,
            _gen_aptot_locales,
        ),
        ExportSpec(
            "reporte_locales",
            "Fotos y PDF de locales",
            ("reporte_locales", "view"),
            ("zip",),
            _parse_reporte_locales,
            _gen_reporte_locales_zip,
            precheck=_precheck_reporte_locales,
        ),
        ExportSpec(
            "item_photos_zip",
            "Fotos de bienes",
            ("imagenes", "view"),
            ("zip",),
            _item_photos.parse_filters,
            _item_photos.generate,
            precheck=_item_photos.precheck,
            describe=_item_photos.describe,
            immutable=True,
            resolve=_item_photos.resolve,
        ),
    )
}


def get_spec(module: str) -> ExportSpec:
    try:
        return SPECS[module]
    except KeyError as exc:
        raise LookupError(f"Exportación desconocida: {module}") from exc


def normalize_format(spec: ExportSpec, export_format: str | None) -> str:
    fmt = (export_format or spec.formats[0]).strip().lower()
    if fmt == "excel":
        fmt = "xlsx"
    if fmt not in spec.formats:
        raise ValueError(f"Formato no disponible para {spec.label}: {fmt}")
    return fmt
