"""API REST de inventario (equivalente a rutas tenant del monolito Laravel)."""

from __future__ import annotations

from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_tenant_id
from app.core.export_storage import read_export_file
from app.modules.iam.dependencies import require_permission
from app.modules.iam.models import User
from app.modules.inventory import conciliation as conc
from app.modules.inventory import conciliation_import_report_pdf as conc_import_pdf
from app.modules.inventory import cost_center_import as cc_import
from app.modules.inventory import list_sbn_import as list_sbn_import_mod
from app.modules.inventory import margesi_import as margesi_import_mod
from app.modules.inventory import person_import as person_import_mod
from app.modules.inventory import environment_import as env_import
from app.modules.inventory import establishment_import as est_import
from app.modules.inventory import cards_import as cards_import_mod
from app.modules.inventory import hoja_captura_import as hoja_captura_import_mod
from app.modules.inventory import descarga_archivos_service as dl_svc
from app.modules.inventory import import_common as imp_common
from app.modules.inventory import geo_catalog as geo
from app.modules.inventory import models as inv_models
from app.modules.inventory.attendance_router import router as attendance_router
from app.modules.inventory import reporte_locales_cronograma_import as rl_cronograma_import
from app.modules.inventory import reporte_locales_download_service as reporte_locales_dl
from app.modules.inventory import reporte_locales_service as reporte_locales
from app.modules.inventory import service as inv
from app.modules.inventory.csv_export import csv_download_response
from app.modules.inventory.export_queries import (
    build_margesi_export_query,
    get_export_query,
)
from app.modules.inventory.schemas import (
    AuditLogQuery,
    CardItemWrite,
    CardWrite,
    ConciliationFilters,
    DescargaArchivoStartResponse,
    DescargaArchivoStatus,
    ConciliationPairWrite,
    ConciliationSbnWrite,
    ConciliationImportReportRequest,
    CostCenterWrite,
    CostCenterImportResult,
    DesconciliarWrite,
    DesconciliarSbnWrite,
    EnvironmentWrite,
    EnvironmentImportResult,
    EstablishmentWrite,
    EstablishmentImportJobStatus,
    EstablishmentImportResult,
    ImportJobStatus,
    HojaCapturaTablesResponse,
    HojaCapturaImportResult,
    HojaCapturaBulkPdfRequest,
    ImportConciliationMatchRequest,
    ImportConciliationResult,
    ImportConciliationRow,
    ImportDesconciliarRequest,
    ImportNoConciliableMatchRequest,
    NoConciliableMarkWrite,
    InventoryDashboardResponse,
    DashboardEstablishmentStatRow,
    DashboardEstablishmentStatsResponse,
    ReporteLocalWrite,
    ActaCierrePdfRequest,
    ReporteLocalCronogramaImportResult,
    ReporteLocalBulkDownloadRequest,
    ReporteLocalSignedUrlResponse,
    ReporteLocalSignedUrlsResponse,
    ReporteLocalesListResponse,
    InventoryUserRegistrationsResponse,
    InventoryNumWrite,
    ItemCardTablesResponse,
    ItemPhotoUploadResult,
    ItemCardTranslate,
    ItemPhotoQuery,
    ItemPhotoRow,
    ListSbnWrite,
    ListSbnImportResult,
    MargesiImportResult,
    MargesiLookupResult,
    MargesiWrite,
    OkPayload,
    PagedMeta,
    PagedRows,
    PersonWrite,
    PersonImportResult,
    RecordQuery,
    UserInventoryConf,
)

router = APIRouter(prefix="/inventory", tags=["inventory"])
router.include_router(attendance_router)


def _csv_export_route(module: str, permission_code: str):
    def _endpoint(
        db: Session = Depends(get_db),
        tenant_id: UUID = Depends(get_tenant_id),
        _: User = Depends(require_permission(permission_code, "export")),
    ):
        try:
            inner_sql, filename_base = get_export_query(module)
            return csv_download_response(
                db,
                tenant_id=tenant_id,
                inner_sql=inner_sql,
                filename_base=filename_base,
            )
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Error al exportar CSV: {exc}") from exc

    return _endpoint


def _q(
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=2000),
    column: str = Query("code"),
    value: str | None = Query(None),
    search: str | None = Query(None, description="Búsqueda en campos principales del módulo"),
    establishment_id: int | None = Query(None, description="Filtrar ambientes por local"),
    column_ord: str | None = Query(None, alias="columnOrd"),
    ord_tipo: str = Query("asc", alias="ordTipo"),
    flag_firma: bool | None = Query(None, description="Filtrar hojas por flag de firma"),
    inv_sit_filter: Literal["C", "S", "N", "F"] | None = Query(
        None,
        description="Margesi: C conciliados, F faltantes, N no inventariable. Bienes: C/S",
    ),
    local_code: str | None = Query(None, description="Filtrar margesi por amb_cod = código de local"),
    export_layout: Literal["full", "report"] | None = Query(
        None,
        description="Export margesi: full=todas las columnas; report=layout operativo",
    ),
    reporte: bool | None = Query(None, description="Filtrar ambientes: true=sí, false=no"),
) -> RecordQuery:
    return RecordQuery(
        page=page,
        per_page=per_page,
        column=column,
        value=value,
        search=search,
        establishment_id=establishment_id,
        column_ord=column_ord,
        ord_tipo=ord_tipo,
        flag_firma=flag_firma,
        inv_sit_filter=inv_sit_filter,
        local_code=local_code,
        export_layout=export_layout,
        reporte=reporte,
    )


def _item_photo_q(
    page: int = Query(1, ge=1),
    per_page: int = Query(24, ge=1, le=200),
    column: str = Query("mar_des"),
    value: str | None = Query(None),
    search: str | None = Query(None, description="Búsqueda por N° inventario, SBN, descripción o hoja"),
    establishment_id: int | None = Query(None, description="Filtrar fotos por local"),
    column_ord: str | None = Query(None, alias="columnOrd"),
    ord_tipo: str = Query("asc", alias="ordTipo"),
    inv_sit_filter: Literal["C", "S"] | None = Query(
        None,
        description="Filtrar bienes: C conciliados, S sobrantes",
    ),
    photo_slot: Literal[1, 2, 3] | None = Query(None, description="Filtrar por slot de foto (1-3)"),
) -> ItemPhotoQuery:
    return ItemPhotoQuery(
        page=page,
        per_page=per_page,
        column=column,
        value=value,
        search=search,
        establishment_id=establishment_id,
        column_ord=column_ord,
        ord_tipo=ord_tipo,
        inv_sit_filter=inv_sit_filter,
        photo_slot=photo_slot,
    )


def _conciliation_q(
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=200),
    column_ord: str | None = Query(None, alias="columnOrd"),
    ord_tipo: str = Query("asc", alias="ordTipo"),
    codigo_interno: str | None = Query(None),
    codigo_sbn: str | None = Query(None),
    descripcion: str | None = Query(None),
    marca: str | None = Query(None),
    modelo: str | None = Query(None),
    local: str | None = Query(None),
    numero_hoja: str | None = Query(None),
    numero_inv: str | None = Query(None),
    situacion: str | None = Query(None, description="todos | conciliable | no_conciliable"),
) -> ConciliationFilters:
    return ConciliationFilters(
        page=page,
        per_page=per_page,
        column_ord=column_ord,
        ord_tipo=ord_tipo,
        codigo_interno=codigo_interno,
        codigo_sbn=codigo_sbn,
        descripcion=descripcion,
        marca=marca,
        modelo=modelo,
        local=local,
        numero_hoja=numero_hoja,
        numero_inv=numero_inv,
        situacion=situacion,
    )


def _audit_q(
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=200),
    column: str = Query("inv_num"),
    value: str | None = Query(None),
    search: str | None = Query(None, description="Búsqueda en usuario, N° inventario, descripción, hoja"),
    column_ord: str | None = Query(None, alias="columnOrd"),
    ord_tipo: str = Query("desc", alias="ordTipo"),
    action: str | None = Query(None, description="create | update | delete"),
    date_from: date | None = Query(None, description="Desde (YYYY-MM-DD)"),
    date_to: date | None = Query(None, description="Hasta (YYYY-MM-DD)"),
) -> AuditLogQuery:
    return AuditLogQuery(
        page=page,
        per_page=per_page,
        column=column,
        value=value,
        search=search,
        column_ord=column_ord,
        ord_tipo=ord_tipo,
        action=action,
        date_from=date_from,
        date_to=date_to,
    )


# --- Catálogo geográfico (Pais / Departamento / Provincia / Distrito) ---


@router.get("/geo/countries")
def geo_countries_list(db: Session = Depends(get_db)):
    return geo.list_countries(db)


@router.get("/geo/departments")
def geo_departments_list(db: Session = Depends(get_db)):
    return geo.list_departments(db)


@router.get("/geo/provinces")
def geo_provinces_list(
    department_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return geo.list_provinces(db, department_id)


@router.get("/geo/districts")
def geo_districts_list(
    province_id: str | None = Query(None),
    db: Session = Depends(get_db),
):
    return geo.list_districts(db, province_id)


# --- Establecimientos ---


@router.get("/establishments/records", response_model=PagedRows)
def establishments_records(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: RecordQuery = Depends(_q),
):
    allowed = {"description", "code", "email", "telephone", "address"}
    rows, total = inv.list_establishments(db, tenant_id, q, allowed)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


router.add_api_route(
    "/establishments/export",
    _csv_export_route("establishments", "locales"),
    methods=["GET"],
    tags=["inventory"],
)


@router.get("/establishments/{row_id}")
def establishment_get(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id)):
    from app.modules.inventory import models as m

    row = db.get(m.InvEstablishment, row_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="No encontrado")
    out = inv.establishment_row_public_dict(row)
    inv._attach_establishment_geo_names(db, [out])
    return out


@router.get("/locales/mapa/situaciones")
def locales_mapa_situaciones(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("locales_mapa", "view")),
):
    from app.modules.inventory import reporte_locales_service as reporte_locales

    return reporte_locales.list_establishment_situaciones(db, tenant_id)


@router.delete("/establishments/{row_id}", response_model=OkPayload)
def establishment_delete(
    row_id: int,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    ok, msg = inv.delete_establishment(db, tenant_id, row_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/establishments", response_model=OkPayload)
def establishment_save(
    body: EstablishmentWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        row = inv.upsert_establishment(db, tenant_id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return OkPayload(success=True, message="Establecimiento guardado", id=row.id)


@router.post("/establishments/import", response_model=EstablishmentImportResult)
async def establishments_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        content, filename = await imp_common.read_upload_bytes(file)
        df = est_import.parse_establishment_upload(content, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.tasks.bulk_imports import import_establishments_task

    result = imp_common.dispatch_import_job(
        db=db,
        content=content,
        filename=filename,
        tenant_id=tenant_id,
        module=imp_common.IMPORT_MODULE_ESTABLISHMENTS,
        row_count=int(len(df)),
        celery_task=import_establishments_task,
        created_by_id=user.id,
    )
    if not result.get("success") and result.get("errors"):
        raise HTTPException(status_code=400, detail=result["errors"][0])
    return EstablishmentImportResult(**result)


@router.get("/import/jobs/{job_id}", response_model=ImportJobStatus)
def import_job_status(
    job_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return ImportJobStatus(**imp_common.get_import_job_status(db, job_id, tenant_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/establishments/import/jobs/{job_id}", response_model=EstablishmentImportJobStatus)
def establishments_import_job_status(
    job_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        payload = imp_common.get_import_job_status(db, job_id, tenant_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return EstablishmentImportJobStatus(
        job_id=payload["job_id"],
        state=payload["state"],
        progress=payload["progress"],
        total_rows=payload["total_rows"],
        processed=payload["processed"],
        inserted=payload["inserted"],
        updated=payload["updated"],
        errors=payload["errors"],
        message=payload["message"],
    )


# --- Personas ---


@router.get("/persons/records", response_model=PagedRows)
def persons_records(db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), q: RecordQuery = Depends(_q)):
    allowed = {
        "name",
        "number",
        "email",
        "telephone",
        "type",
        "enviroment_code",
        "cc_code",
        "identity_document_type_id",
    }
    rows, total = inv.list_persons(db, tenant_id, q, allowed)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


router.add_api_route(
    "/persons/export",
    _csv_export_route("persons", "personas"),
    methods=["GET"],
    tags=["inventory"],
)


@router.get("/persons/{row_id}")
def person_get(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id)):
    from app.modules.inventory import models as m

    row = db.get(m.InvPerson, row_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="No encontrado")
    return inv.inventory_row_dict(row)


@router.post("/persons", response_model=OkPayload)
def person_save(
    body: PersonWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        row = inv.upsert_person(db, tenant_id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return OkPayload(success=True, message="Persona guardada", id=row.id)


@router.delete("/persons/{row_id}", response_model=OkPayload)
def person_delete(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user)):
    ok, msg = inv.delete_person(db, tenant_id, row_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/persons/import", response_model=PersonImportResult)
async def persons_import(
    file: UploadFile = File(...),
    type: str = Query("customers", description="Tipo de persona para todas las filas (ej. customers, suppliers)"),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        content, filename = await imp_common.read_upload_bytes(file)
        df, _ = person_import_mod.parse_person_data_rows(content, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.tasks.bulk_imports import import_persons_task

    result = imp_common.dispatch_import_job(
        db=db,
        content=content,
        filename=filename,
        tenant_id=tenant_id,
        module=imp_common.IMPORT_MODULE_PERSONS,
        row_count=int(len(df)),
        celery_task=import_persons_task,
        celery_args=(type,),
        created_by_id=user.id,
        extra={"person_type": type},
    )
    if not result.get("success") and result.get("errors"):
        raise HTTPException(status_code=400, detail=result["errors"][0])
    return PersonImportResult(**result)


# --- Centros de costo ---


@router.get("/cost-centers/records", response_model=PagedRows)
def cost_centers_records(
    db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), q: RecordQuery = Depends(_q)
):
    allowed = {"code", "description"}
    rows, total = inv.list_cost_centers(db, tenant_id, q, allowed)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


router.add_api_route(
    "/cost-centers/export",
    _csv_export_route("cost_centers", "centro_costo"),
    methods=["GET"],
    tags=["inventory"],
)


@router.get("/cost-centers/{row_id}")
def cost_center_get(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id)):
    from app.modules.inventory import models as m

    row = db.get(m.InvCostCenter, row_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="No encontrado")
    return inv.inventory_row_dict(row)


@router.post("/cost-centers", response_model=OkPayload)
def cost_center_save(
    body: CostCenterWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        row = inv.upsert_cost_center(db, tenant_id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return OkPayload(success=True, message="Centro de costo guardado", id=row.id)


@router.post("/cost-centers/import", response_model=CostCenterImportResult)
async def cost_centers_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        content, filename = await imp_common.read_upload_bytes(file)
        df, _ = cc_import.parse_cost_center_data_rows(content, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.tasks.bulk_imports import import_cost_centers_task

    result = imp_common.dispatch_import_job(
        db=db,
        content=content,
        filename=filename,
        tenant_id=tenant_id,
        module=imp_common.IMPORT_MODULE_COST_CENTERS,
        row_count=int(len(df)),
        celery_task=import_cost_centers_task,
        created_by_id=user.id,
    )
    if not result.get("success") and result.get("errors"):
        raise HTTPException(status_code=400, detail=result["errors"][0])
    return CostCenterImportResult(**result)


@router.delete("/cost-centers/{row_id}", response_model=OkPayload)
def cost_center_delete(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user)):
    ok, msg = inv.delete_cost_center(db, tenant_id, row_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


# --- Ambientes ---


@router.get("/environments/records", response_model=PagedRows)
def environments_records(
    db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), q: RecordQuery = Depends(_q)
):
    allowed = {"code", "description", "floor", "telephone"}
    rows, total = inv.list_environments(db, tenant_id, q, allowed)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


router.add_api_route(
    "/environments/export",
    _csv_export_route("environments", "ambientes"),
    methods=["GET"],
    tags=["inventory"],
)


@router.get("/environments/{row_id}")
def environment_get(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id)):
    from app.modules.inventory import models as m

    row = db.get(m.InvEnvironment, row_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="No encontrado")
    return inv.inventory_row_dict(row)


@router.post("/environments", response_model=OkPayload)
def environment_save(
    body: EnvironmentWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        inv.upsert_environment(db, tenant_id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return OkPayload(success=True, message="Ambiente actualizada")


@router.post("/environments/import", response_model=EnvironmentImportResult)
async def environments_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        content, filename = await imp_common.read_upload_bytes(file)
        df, _ = env_import.parse_environment_data_rows(content, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.tasks.bulk_imports import import_environments_task

    result = imp_common.dispatch_import_job(
        db=db,
        content=content,
        filename=filename,
        tenant_id=tenant_id,
        module=imp_common.IMPORT_MODULE_ENVIRONMENTS,
        row_count=int(len(df)),
        celery_task=import_environments_task,
        created_by_id=user.id,
    )
    if not result.get("success") and result.get("errors"):
        raise HTTPException(status_code=400, detail=result["errors"][0])
    return EnvironmentImportResult(**result)


@router.delete("/environments/{row_id}", response_model=OkPayload)
def environment_delete(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user)):
    ok, msg = inv.delete_environment(db, tenant_id, row_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


# --- Hojas de captura (cards) ---


@router.get("/cards/records", response_model=PagedRows)
def cards_records(db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), q: RecordQuery = Depends(_q)):
    allowed = {"hoj_num", "state", "nota_interna"}
    rows, total = inv.list_cards(db, tenant_id, q, allowed)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.post("/hoja-captura/export", response_model=DescargaArchivoStartResponse)
def hoja_captura_export_start(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(require_permission("hoja_captura", "export")),
    q: RecordQuery = Depends(_q),
):
    """Encola exportación Excel: Celery genera XLSX, lo sube a GCS y guarda URL en ``descarga_archivos``."""
    return DescargaArchivoStartResponse(
        **dl_svc.schedule_hoja_captura_export(
            db,
            tenant_id=tenant_id,
            q=q,
            created_by_id=user.id,
        ),
    )


@router.get("/hoja-captura/export")
def hoja_captura_export_get_not_allowed():
    raise HTTPException(
        status_code=405,
        detail=(
            "La exportación de hoja de captura es asíncrona. Use POST /api/inventory/hoja-captura/export "
            "para encolar el trabajo y consulte GET /hoja-captura/export/{job_id} para el estado."
        ),
    )


@router.get("/hoja-captura/export/{job_id}", response_model=DescargaArchivoStatus)
def hoja_captura_export_status(
    job_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("hoja_captura", "export")),
):
    try:
        return DescargaArchivoStatus(**dl_svc.get_descarga_archivo_status(db, job_id, tenant_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/cards/{row_id}")
def card_get(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id)):
    from app.modules.inventory import models as m

    row = db.get(m.InvCard, row_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="No encontrado")
    return inv.inventory_row_dict(row)


@router.post("/cards", response_model=OkPayload)
def card_save(
    body: CardWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        row = inv.upsert_card(db, tenant_id, body, user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return OkPayload(success=True, message="Hoja de captura actualizada", id=row.id)


@router.post("/cards/{card_id}/items", response_model=OkPayload)
def card_add_item(
    card_id: int,
    body: CardItemWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    ok, msg = inv.store_card_item(db, tenant_id, card_id, body, operator_id=user.id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/cards/recount-items", response_model=OkPayload)
def cards_recount(db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user)):
    inv.recount_card_items(db, tenant_id)
    return OkPayload(success=True, message="Conteos actualizados")


@router.patch("/cards/{card_id}/close", response_model=OkPayload)
def card_close(card_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user)):
    ok, msg = inv.close_card(db, tenant_id, card_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.patch("/cards/{card_id}/open", response_model=OkPayload)
def card_open(card_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user)):
    ok, msg = inv.open_card(db, tenant_id, card_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


# --- Hoja de captura (alias producción) ---


@router.get("/hoja-captura/tables", response_model=HojaCapturaTablesResponse)
def hoja_captura_tables(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    return inv.hoja_captura_tables(db, tenant_id, user.id)


@router.post("/hoja-captura/import", response_model=HojaCapturaImportResult)
async def hoja_captura_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        content, filename = await imp_common.read_upload_bytes(file)
        df, _ = hoja_captura_import_mod.parse_hoja_captura_item_rows(content, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.tasks.bulk_imports import import_hoja_captura_task

    result = imp_common.dispatch_import_job(
        db=db,
        content=content,
        filename=filename,
        tenant_id=tenant_id,
        module=imp_common.IMPORT_MODULE_HOJA_CAPTURA,
        row_count=int(len(df)),
        celery_task=import_hoja_captura_task,
        created_by_id=user.id,
    )
    if not result.get("success") and result.get("errors"):
        raise HTTPException(status_code=400, detail=result["errors"][0])
    return HojaCapturaImportResult(**result)


@router.post("/hoja-captura/cards/import", response_model=HojaCapturaImportResult)
async def hoja_captura_cards_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        content, filename = await imp_common.read_upload_bytes(file)
        df, _ = cards_import_mod.parse_cards_data_rows(content, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.tasks.bulk_imports import import_cards_task

    result = imp_common.dispatch_import_job(
        db=db,
        content=content,
        filename=filename,
        tenant_id=tenant_id,
        module=imp_common.IMPORT_MODULE_CARDS,
        row_count=int(len(df)),
        celery_task=import_cards_task,
        created_by_id=user.id,
    )
    if not result.get("success") and result.get("errors"):
        raise HTTPException(status_code=400, detail=result["errors"][0])
    return HojaCapturaImportResult(**result)


@router.get("/hoja-captura/tables/user", response_model=UserInventoryConf)
def hoja_captura_tables_user(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    from app.modules.iam.models import User as UserModel

    row = db.get(UserModel, user.id)
    return inv.user_inventory_conf(row)


@router.get("/hoja-captura/item/tables", response_model=ItemCardTablesResponse)
def hoja_captura_item_tables(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    return inv.item_card_tables(db, tenant_id, user.id)


@router.post("/hoja-captura/uploads/{inv_num}/{slot}", response_model=ItemPhotoUploadResult)
async def hoja_captura_upload_item_photo(
    inv_num: str,
    slot: int,
    file: UploadFile = File(...),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    if not (inv_num or "").strip():
        raise HTTPException(status_code=400, detail="Número de inventario requerido para subir foto")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Archivo vacío")
    try:
        url = inv.save_hoja_captura_item_photo(
            tenant_id, inv_num, slot, content, file.filename or "foto.jpg"
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ItemPhotoUploadResult(
        success=True,
        message="Foto guardada",
        url=url,
        filename=url.rsplit("/", 1)[-1] if url else None,
    )


@router.get("/hoja-captura/item-photo/preview")
def hoja_captura_item_photo_preview(
    src: str = Query(..., min_length=1),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    from app.core.item_photo_storage import read_item_photo_bytes

    result = read_item_photo_bytes(src, tenant_id)
    if not result:
        raise HTTPException(status_code=404, detail="Foto no encontrada")
    data, mime = result
    return Response(content=data, media_type=mime)


@router.get("/hoja-captura/item/record/{card_id}", response_model=PagedRows)
def hoja_captura_item_record(
    card_id: int,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: RecordQuery = Depends(_q),
):
    q = RecordQuery(
        page=q.page,
        per_page=min(q.per_page, 500),
        column="id_card",
        value=str(card_id),
        column_ord=q.column_ord or "id",
        ord_tipo=q.ord_tipo,
    )
    allowed = {"inv_num", "mar_cpat", "mar_num", "mar_des", "inv_sit", "id_card"}
    rows, total = inv.list_item_cards(db, tenant_id, q, allowed | {"num_card"})
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.post("/hoja-captura/edit/item", response_model=OkPayload)
def hoja_captura_edit_item(
    body: CardItemWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    ok, msg = inv.edit_card_item(db, tenant_id, body, operator_id=user.id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/hoja-captura/move/{item_id}", response_model=OkPayload)
def hoja_captura_move_item(
    item_id: int,
    body: ItemCardTranslate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    ok, msg = inv.translate_item_card(db, tenant_id, item_id, body)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/hoja-captura/num", response_model=UserInventoryConf)
def hoja_captura_update_num(
    body: InventoryNumWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        row = inv.update_user_inventory_num(db, tenant_id, user.id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return inv.user_inventory_conf(row)


@router.post("/hoja-captura/contarBienes", response_model=OkPayload)
def hoja_captura_contar_bienes(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    inv.recount_card_items(db, tenant_id)
    return OkPayload(success=True, message="Conteos actualizados")


@router.post("/hoja-captura/close/{card_id}", response_model=OkPayload)
def hoja_captura_close(
    card_id: int,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    ok, msg = inv.close_card(db, tenant_id, card_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/hoja-captura/pdf-fichas/bulk")
def hoja_captura_bulk_pdf_fichas(
    body: HojaCapturaBulkPdfRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        pdf_bytes, filename = inv.build_hoja_captura_bulk_ficha_pdf(
            db,
            tenant_id,
            mode=body.mode,
            hoj_num_from=body.hoj_num_from,
            hoj_num_to=body.hoj_num_to,
            establishment_id=body.establishment_id,
            person_id=body.person_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error al generar PDF: {exc}") from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/hoja-captura/{card_id}/pdf-ficha")
def hoja_captura_pdf_ficha(
    card_id: int,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        pdf_bytes, filename = inv.build_hoja_captura_ficha_pdf(db, tenant_id, card_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error al generar PDF: {exc}") from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/margesi/item/{valor}/{tipo}", response_model=MargesiLookupResult)
def margesi_lookup(
    valor: str,
    tipo: str,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    data = inv.record_margesi_cod(db, tenant_id, valor, tipo, user.id)
    return MargesiLookupResult(**data)


# --- Bienes (itemcards) ---


@router.get("/item-photos/records", response_model=PagedRows)
def item_photos_records(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: ItemPhotoQuery = Depends(_item_photo_q),
    _: User = Depends(require_permission("imagenes", "view")),
):
    rows, total = inv.list_item_photos(db, tenant_id, q)
    return PagedRows(
        data=[ItemPhotoRow(**r).model_dump() for r in rows],
        meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)),
    )


@router.get("/item-cards/records", response_model=PagedRows)
def item_cards_records(
    db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), q: RecordQuery = Depends(_q)
):
    allowed = {"inv_num", "mar_cpat", "mar_num", "mar_des", "inv_sit", "id_card"}
    rows, total = inv.list_item_cards(db, tenant_id, q, allowed | {"num_card"})
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.post("/item-cards/export", response_model=DescargaArchivoStartResponse)
def item_cards_export_start(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(require_permission("bienes", "export")),
    q: RecordQuery = Depends(_q),
    export_format: Literal["csv", "xlsx"] = Query("csv", description="Formato del archivo: csv o xlsx"),
):
    """Encola exportación de bienes: Celery genera CSV/XLSX, lo sube a GCS y guarda URL en ``descarga_archivos``."""
    return DescargaArchivoStartResponse(
        **dl_svc.schedule_item_cards_export(
            db,
            tenant_id=tenant_id,
            q=q,
            export_format=export_format,
            created_by_id=user.id,
        ),
    )


@router.get("/item-cards/export")
def item_cards_export_get_not_allowed():
    """Evita que GET /export caiga en ``/item-cards/{row_id}`` con row_id='export'."""
    raise HTTPException(
        status_code=405,
        detail=(
            "La exportación de bienes es asíncrona. Use POST /api/inventory/item-cards/export "
            "para encolar el trabajo y consulte GET /item-cards/export/{job_id} para el estado."
        ),
    )


@router.get("/item-cards/export/{job_id}", response_model=DescargaArchivoStatus)
def item_cards_export_status(
    job_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("bienes", "export")),
):
    try:
        return DescargaArchivoStatus(**dl_svc.get_descarga_archivo_status(db, job_id, tenant_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/item-cards/{row_id}")
def item_card_get(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id)):
    from app.modules.inventory import models as m

    row = db.get(m.InvItemCard, row_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="No encontrado")
    return inv.inventory_row_dict(row)


@router.post("/item-cards/{item_id}/translate", response_model=OkPayload)
def item_card_translate(
    item_id: int,
    body: ItemCardTranslate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    ok, msg = inv.translate_item_card(db, tenant_id, item_id, body)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.delete("/item-cards/{item_id}", response_model=OkPayload)
def item_card_delete(
    item_id: int,
    id_card: int = Query(..., description="ID de la hoja (`BienesController::destroy`)"),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    ok, msg = inv.delete_item_card(db, tenant_id, item_id, id_card, operator_id=user.id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


# --- Catálogo SBN ---


@router.get("/list-sbn/records", response_model=PagedRows)
def list_sbn_records(db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), q: RecordQuery = Depends(_q)):
    allowed = {"code", "cat_des", "cat_clase", "cat_cat"}
    rows, total = inv.list_list_sbn(db, tenant_id, q, allowed)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


router.add_api_route(
    "/list-sbn/export",
    _csv_export_route("list_sbn", "list_sbn"),
    methods=["GET"],
    tags=["inventory"],
)


@router.get("/list-sbn/{row_id}")
def list_sbn_get(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id)):
    from app.modules.inventory import models as m

    row = db.get(m.InvListSbn, row_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="No encontrado")
    return inv.inventory_row_dict(row)


@router.post("/list-sbn", response_model=OkPayload)
def list_sbn_save(
    body: ListSbnWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        row = inv.upsert_list_sbn(db, tenant_id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return OkPayload(success=True, message="Catálogo SBN guardado", id=row.id)


@router.delete("/list-sbn/{row_id}", response_model=OkPayload)
def list_sbn_delete(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user)):
    ok, msg = inv.delete_list_sbn(db, tenant_id, row_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/list-sbn/import", response_model=ListSbnImportResult)
async def list_sbn_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        content, filename = await imp_common.read_upload_bytes(file)
        df, _ = list_sbn_import_mod.parse_list_sbn_data_rows(content, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.tasks.bulk_imports import import_list_sbn_task

    result = imp_common.dispatch_import_job(
        db=db,
        content=content,
        filename=filename,
        tenant_id=tenant_id,
        module=imp_common.IMPORT_MODULE_LIST_SBN,
        row_count=int(len(df)),
        celery_task=import_list_sbn_task,
        created_by_id=user.id,
    )
    if not result.get("success") and result.get("errors"):
        raise HTTPException(status_code=400, detail=result["errors"][0])
    return ListSbnImportResult(**result)


# --- Margesi (patrimonio) ---


@router.get("/margesi/records", response_model=PagedRows)
def margesi_records(db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), q: RecordQuery = Depends(_q)):
    allowed = {"inv_num", "mar_cpat", "mar_des", "inv_sit", "mar_num", "mar_mar", "mar_mod"}
    rows, total = inv.list_margesi(db, tenant_id, q, allowed)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.get("/margesi/export")
def margesi_export(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: RecordQuery = Depends(_q),
    _: User = Depends(require_permission("margesi", "export")),
):
    """Export CSV de margesi; acepta ``search`` e ``inv_sit_filter`` como el listado (COPY en PostgreSQL)."""
    try:
        inner_sql, params, filename_base = build_margesi_export_query(tenant_id, q)
        return csv_download_response(
            db,
            tenant_id=tenant_id,
            inner_sql=inner_sql,
            filename_base=filename_base,
            params=params,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error al exportar CSV: {exc}") from exc


@router.get("/margesi/{row_id}")
def margesi_get(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id)):
    from app.modules.inventory import models as m
    from app.modules.inventory.margesi_mapper import margesi_row_to_api

    row = db.get(m.InvMargesiItem, row_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="No encontrado")
    return margesi_row_to_api(row)


@router.post("/margesi", response_model=OkPayload)
def margesi_save(
    body: MargesiWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        row = inv.upsert_margesi(db, tenant_id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return OkPayload(success=True, message="Registro margesi guardado", id=row.id)


@router.delete("/margesi/{row_id}", response_model=OkPayload)
def margesi_delete(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), _: User = Depends(get_current_user)):
    ok, msg = inv.delete_margesi(db, tenant_id, row_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/margesi/import", response_model=MargesiImportResult)
async def margesi_import(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        content, filename = await imp_common.read_upload_bytes(file)
        df, _ = margesi_import_mod.parse_margesi_data_rows(content, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.tasks.bulk_imports import import_margesi_task

    result = imp_common.dispatch_import_job(
        db=db,
        content=content,
        filename=filename,
        tenant_id=tenant_id,
        module=imp_common.IMPORT_MODULE_MARGESI,
        row_count=int(len(df)),
        celery_task=import_margesi_task,
        created_by_id=user.id,
    )
    if not result.get("success") and result.get("errors"):
        raise HTTPException(status_code=400, detail=result["errors"][0])
    return MargesiImportResult(**result)


@router.post("/margesi/import-moment", response_model=MargesiImportResult)
async def margesi_import_moment(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        content, filename = await imp_common.read_upload_bytes(file)
        df, _ = margesi_import_mod.parse_margesi_moment_rows(content, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from app.tasks.bulk_imports import import_margesi_moment_task

    result = imp_common.dispatch_import_job(
        db=db,
        content=content,
        filename=filename,
        tenant_id=tenant_id,
        module=imp_common.IMPORT_MODULE_MARGESI_MOMENT,
        row_count=int(len(df)),
        celery_task=import_margesi_moment_task,
        created_by_id=user.id,
    )
    if not result.get("success") and result.get("errors"):
        raise HTTPException(status_code=400, detail=result["errors"][0])
    return MargesiImportResult(**result)


# --- Auditoría de bienes ---


@router.get("/audit-logs/records", response_model=PagedRows)
def audit_log_records(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
    q: AuditLogQuery = Depends(_audit_q),
):
    allowed = {
        "action",
        "inv_num",
        "mar_des",
        "user_full_name",
        "user_email",
        "hoj_num",
        "itemcard_id",
        "card_id",
    }
    rows, total = inv.list_item_audit_logs(db, tenant_id, q, allowed)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


# --- Dashboard inventario ---


@router.get("/dashboard", response_model=InventoryDashboardResponse)
def inventory_dashboard(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    establishment_id: int | None = Query(None, description="Filtrar por local (establishment id)"),
    date_from: date | None = Query(None, description="Inicio del periodo (YYYY-MM-DD)"),
    date_to: date | None = Query(None, description="Fin del periodo (YYYY-MM-DD)"),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$", description="Filtrar un mes (YYYY-MM)"),
):
    return inv.inventory_dashboard(
        db,
        tenant_id,
        establishment_id=establishment_id,
        date_from=date_from,
        date_to=date_to,
        month=month,
    )


@router.get("/dashboard/user-registrations", response_model=InventoryUserRegistrationsResponse)
def inventory_user_registrations(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    establishment_id: int | None = Query(None, description="Filtrar por local (establishment id)"),
    date_from: date | None = Query(None, description="Inicio del periodo (YYYY-MM-DD)"),
    date_to: date | None = Query(None, description="Fin del periodo (YYYY-MM-DD)"),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$", description="Filtrar un mes (YYYY-MM)"),
):
    return inv.inventory_user_registrations(
        db,
        tenant_id,
        establishment_id=establishment_id,
        date_from=date_from,
        date_to=date_to,
        month=month,
    )


@router.get("/dashboard/establishment-stats", response_model=DashboardEstablishmentStatsResponse)
def inventory_dashboard_establishment_stats(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    search: str | None = Query(None, description="Filtrar por código o nombre de local"),
    live: bool = Query(False, description="Calcular en vivo sin usar cache materializado"),
):
    return inv.inventory_dashboard_establishment_stats(
        db,
        tenant_id,
        page=page,
        per_page=per_page,
        search=search,
        live=live,
    )


@router.post("/dashboard/establishment-stats/refresh", response_model=OkPayload)
def inventory_dashboard_establishment_stats_refresh(
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("dashboard", "view")),
):
    from app.modules.inventory.dashboard_establishment_stats_cache import (
        schedule_dashboard_establishment_stats_tenant_refresh,
    )

    schedule_dashboard_establishment_stats_tenant_refresh(tenant_id)
    return OkPayload(success=True, message="Actualización del resumen por local encolada")


@router.get("/reporte-locales/records", response_model=ReporteLocalesListResponse)
def reporte_locales_records(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_locales", "view")),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    search: str | None = Query(None, description="Filtrar por código o nombre de local"),
):
    return reporte_locales.list_reporte_locales(
        db,
        tenant_id,
        page=page,
        per_page=per_page,
        search=search,
    )


@router.post("/reporte-locales", response_model=OkPayload)
def reporte_locales_save(
    body: ReporteLocalWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_locales", "edit")),
):
    try:
        reporte_locales.upsert_reporte_local(db, tenant_id, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return OkPayload(success=True, message="Seguimiento del local guardado")


@router.post("/reporte-locales/import-cronograma", response_model=ReporteLocalCronogramaImportResult)
async def reporte_locales_import_cronograma(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_locales", "edit")),
):
    try:
        content, filename = await imp_common.read_upload_bytes(file)
        result = rl_cronograma_import.bulk_import_cronograma(db, tenant_id, content, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not result.get("success") and result.get("errors"):
        raise HTTPException(status_code=400, detail=result["errors"][0])
    return ReporteLocalCronogramaImportResult(**result)


@router.post("/reporte-locales/uploads/{establishment_id}/foto", response_model=ItemPhotoUploadResult)
async def reporte_locales_upload_foto(
    establishment_id: int,
    file: UploadFile = File(...),
    current: int = Query(0, ge=0, le=5, description="Cantidad actual en el formulario"),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_locales", "edit")),
):
    content = await file.read()
    try:
        url = reporte_locales.upload_reporte_local_foto_file(
            db,
            tenant_id,
            establishment_id,
            content,
            current_count=current,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ItemPhotoUploadResult(
        success=True,
        message="Foto guardada",
        url=url,
        filename=url.rsplit("/", 1)[-1] if url else None,
    )


@router.post("/reporte-locales/uploads/{establishment_id}/pdf", response_model=ItemPhotoUploadResult)
async def reporte_locales_upload_pdf(
    establishment_id: int,
    file: UploadFile = File(...),
    current: int = Query(0, ge=0, le=2, description="Cantidad actual en el formulario"),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_locales", "edit")),
):
    content = await file.read()
    try:
        url = reporte_locales.upload_reporte_local_pdf_file(
            db,
            tenant_id,
            establishment_id,
            content,
            file.filename or "documento.pdf",
            current_count=current,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ItemPhotoUploadResult(
        success=True,
        message="PDF guardado",
        url=url,
        filename=file.filename or url.rsplit("/", 1)[-1] if url else None,
    )


@router.get("/reporte-locales/file/preview")
def reporte_locales_file_preview(
    src: str = Query(..., min_length=1),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_locales", "view")),
):
    try:
        data, mime = reporte_locales.read_reporte_local_file_preview(src, tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(content=data, media_type=mime)


@router.get("/reporte-locales/download/signed-url", response_model=ReporteLocalSignedUrlResponse)
def reporte_locales_download_signed_url(
    src: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_locales", "view")),
):
    try:
        return ReporteLocalSignedUrlResponse(**reporte_locales_dl.get_single_signed_url(db, tenant_id, src=src))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reporte-locales/download/file")
def reporte_locales_download_file(
    src: str = Query(..., min_length=1),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_locales", "view")),
):
    """Descarga autenticada para archivos en disco local (desarrollo sin GCS)."""
    try:
        data, mime = reporte_locales.read_reporte_local_file_preview(src, tenant_id)
        filename = reporte_locales_dl.resolve_stored_url_download_filename(db, tenant_id, src)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reporte-locales/{establishment_id}/download-urls", response_model=ReporteLocalSignedUrlsResponse)
def reporte_locales_establishment_download_urls(
    establishment_id: int,
    kind: Literal["all", "fotos", "pdfs"] = Query("all"),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_locales", "view")),
):
    try:
        return ReporteLocalSignedUrlsResponse(
            **reporte_locales_dl.get_establishment_signed_urls(
                db,
                tenant_id,
                establishment_id,
                kind=kind,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reporte-locales/download/bulk", response_model=DescargaArchivoStartResponse)
def reporte_locales_bulk_download_start(
    body: ReporteLocalBulkDownloadRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(require_permission("reporte_locales", "view")),
):
    try:
        return DescargaArchivoStartResponse(
            **reporte_locales_dl.schedule_bulk_download(
                db,
                tenant_id=tenant_id,
                establishment_ids=body.establishment_ids,
                department_id=body.department_id,
                include_fotos=body.include_fotos,
                include_pdfs=body.include_pdfs,
                created_by_id=user.id,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/reporte-locales/download/bulk/{job_id}", response_model=DescargaArchivoStatus)
def reporte_locales_bulk_download_status(
    job_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_locales", "view")),
):
    try:
        status = dl_svc.get_descarga_archivo_status(db, job_id, tenant_id)
        if status.get("module") != "reporte_locales":
            raise LookupError("Trabajo de descarga no encontrado")
        return DescargaArchivoStatus(**status)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reporte-locales/{establishment_id}/stats", response_model=DashboardEstablishmentStatRow)
def reporte_locales_stats(
    establishment_id: int,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_locales", "view")),
):
    try:
        return reporte_locales.get_reporte_local_stats(db, tenant_id, establishment_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reporte-locales/{establishment_id}/pdf-acta-cierre")
def reporte_locales_pdf_acta_cierre(
    establishment_id: int,
    body: ActaCierrePdfRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_locales", "view")),
):
    """Genera PDF del Anexo 005 – Acta de Cierre para un local."""
    try:
        pdf_bytes, filename = reporte_locales.build_acta_cierre_pdf(
            db,
            tenant_id,
            establishment_id,
            body,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error al generar acta de cierre: {exc}") from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reporte-aptot/cache-meta")
def reporte_aptot_cache_meta(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_aptot", "view")),
):
    return inv.get_reporte_aptot_cache_meta(db, tenant_id)


@router.post("/reporte-aptot/refresh", response_model=OkPayload)
def reporte_aptot_refresh(
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_aptot", "edit")),
):
    from app.modules.inventory.reporte_aptot_cache import schedule_reporte_aptot_cache_refresh

    schedule_reporte_aptot_cache_refresh(tenant_id)
    return OkPayload(success=True, message="Actualización del reporte APTOT encolada")


@router.post("/reporte-aptot/export", response_model=DescargaArchivoStartResponse)
def reporte_aptot_export_start(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(require_permission("reporte_aptot", "export")),
):
    """Encola exportación APTOT: Celery genera CSV, lo sube a GCS y guarda URL en ``descarga_archivos``."""
    return DescargaArchivoStartResponse(**dl_svc.schedule_reporte_aptot_export(db, tenant_id=tenant_id, created_by_id=user.id))


@router.get("/reporte-aptot/export/{job_id}", response_model=DescargaArchivoStatus)
def reporte_aptot_export_status(
    job_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_aptot", "export")),
):
    try:
        return DescargaArchivoStatus(**dl_svc.get_descarga_archivo_status(db, job_id, tenant_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reporte-aptot-locales/{establishment_id}/export-meta")
def reporte_aptot_locales_export_meta(
    establishment_id: int,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_aptot_locales", "view")),
    export_format: Literal["csv", "xlsx"] = Query("csv", description="Formato del último reporte generado"),
):
    try:
        return inv.get_reporte_aptot_locales_export_meta(
            db,
            tenant_id,
            establishment_id,
            export_format=export_format,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reporte-aptot-locales/{establishment_id}/cache-meta")
def reporte_aptot_locales_cache_meta(
    establishment_id: int,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_aptot_locales", "view")),
    export_format: Literal["csv", "xlsx"] = Query("csv"),
):
    """Retrocompatible; delega en ``export-meta``."""
    try:
        return inv.get_reporte_aptot_locales_export_meta(
            db,
            tenant_id,
            establishment_id,
            export_format=export_format,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reporte-aptot-locales/{establishment_id}/export", response_model=DescargaArchivoStartResponse)
def reporte_aptot_locales_export_start(
    establishment_id: int,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(require_permission("reporte_aptot_locales", "export")),
    export_format: Literal["csv", "xlsx"] = Query("csv", description="Formato del archivo: csv o xlsx"),
):
    try:
        return DescargaArchivoStartResponse(
            **dl_svc.schedule_reporte_aptot_locales_export(
                db,
                tenant_id=tenant_id,
                establishment_id=establishment_id,
                export_format=export_format,
                created_by_id=user.id,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/reporte-aptot-locales/export/{job_id}", response_model=DescargaArchivoStatus)
def reporte_aptot_locales_export_status(
    job_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("reporte_aptot_locales", "export")),
):
    try:
        return DescargaArchivoStatus(**dl_svc.get_descarga_archivo_status(db, job_id, tenant_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/descarga-archivos/{job_id}/file")
def descarga_archivo_file(
    job_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    """Proxy de descarga para exportaciones almacenadas en disco local (desarrollo sin GCS)."""
    from app.modules.iam.dependencies import _has_action

    row = dl_svc.get_descarga_archivo(db, job_id, tenant_id)
    if row is None or row.state != "success" or not row.gcs_path:
        raise HTTPException(status_code=404, detail="Archivo no disponible")

    module_perm: tuple[str, str] | None = {
        "reporte_aptot": ("reporte_aptot", "export"),
        "reporte_aptot_locales": ("reporte_aptot_locales", "export"),
        "reporte_locales": ("reporte_locales", "view"),
        "item_cards": ("bienes", "export"),
        "hoja_captura": ("hoja_captura", "export"),
    }.get(row.module)
    if module_perm is None:
        raise HTTPException(status_code=404, detail="Archivo no disponible")
    code, action = module_perm
    if not _has_action(user, db, tenant_id, code, action):  # type: ignore[arg-type]
        raise HTTPException(status_code=403, detail="No tiene permiso para esta acción")

    try:
        content = read_export_file(row.gcs_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"No se pudo leer el archivo: {exc}") from exc

    if row.filename.lower().endswith(".zip"):
        media_type = "application/zip"
    elif row.filename.lower().endswith(".csv"):
        media_type = "text/csv; charset=utf-8"
    elif row.filename.lower().endswith(".xlsx"):
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    else:
        media_type = "application/octet-stream"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{row.filename}"'},
    )


# --- Conciliación ---


@router.get("/conciliation/columns")
def conciliation_columns():
    return {
        "mar_des": "Descripción",
        "inv_num": "Número de Inventario",
        "mar_cpat": "Código SBN",
        "num_card": "Número de Hoja",
    }


@router.get("/conciliation/margesi-records", response_model=PagedRows)
def conciliation_margesi_records(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: ConciliationFilters = Depends(_conciliation_q),
):
    rows, total = conc.list_pending_margesi(db, tenant_id, q)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.get("/conciliation/bienes-records", response_model=PagedRows)
def conciliation_bienes_records(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: ConciliationFilters = Depends(_conciliation_q),
):
    rows, total = conc.list_pending_bienes(db, tenant_id, q)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.get("/conciliation/conciliados-records", response_model=PagedRows)
def conciliation_conciliados_records(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: ConciliationFilters = Depends(_conciliation_q),
):
    rows, total = conc.list_conciliated_bienes(db, tenant_id, q)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.get("/conciliation/no-conciliables-records", response_model=PagedRows)
def conciliation_no_conciliables_records(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: ConciliationFilters = Depends(_conciliation_q),
):
    rows, total = conc.list_no_conciliables(db, tenant_id, q)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.get("/conciliation/desconciliacion/margesi-records", response_model=PagedRows)
def conciliation_desconciliacion_margesi(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: ConciliationFilters = Depends(_conciliation_q),
):
    rows, total = conc.list_conciliated_margesi(db, tenant_id, q)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.get("/conciliation/no-conciliation/margesi-records", response_model=PagedRows)
def conciliation_no_conciliation_margesi(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: ConciliationFilters = Depends(_conciliation_q),
):
    rows, total = conc.list_no_conciliation_margesi(db, tenant_id, q)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.get("/conciliation/no-conciliation/bienes-records", response_model=PagedRows)
def conciliation_no_conciliation_bienes(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: ConciliationFilters = Depends(_conciliation_q),
):
    rows, total = conc.list_no_conciliation_bienes(db, tenant_id, q)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.get("/conciliation/sbn/margesi-records", response_model=PagedRows)
def conciliation_sbn_margesi_records(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: ConciliationFilters = Depends(_conciliation_q),
):
    rows, total = conc.list_pending_margesi(db, tenant_id, q)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.get("/conciliation/sbn/bienes-records", response_model=PagedRows)
def conciliation_sbn_bienes_records(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: ConciliationFilters = Depends(_conciliation_q),
):
    rows, total = conc.list_pending_bienes(db, tenant_id, q)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.get("/conciliation/desconciliacion-sbn/margesi-records", response_model=PagedRows)
def conciliation_desconciliacion_sbn_margesi(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: ConciliationFilters = Depends(_conciliation_q),
):
    rows, total = conc.list_desconciliacion_sbn_margesi(db, tenant_id, q)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.get("/conciliation/desconciliacion-sbn/bienes-records", response_model=PagedRows)
def conciliation_desconciliacion_sbn_bienes(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    q: ConciliationFilters = Depends(_conciliation_q),
):
    rows, total = conc.list_desconciliacion_sbn_bienes(db, tenant_id, q)
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.post("/conciliation", response_model=OkPayload)
def conciliation_store(
    body: ConciliationPairWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    ok, msg = conc.conciliar_pair(db, tenant_id, body.margesi, body.bienes)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/conciliation/desconciliar", response_model=OkPayload)
def conciliation_desconciliar(
    body: DesconciliarWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    ok, msg = conc.desconciliar_item(db, tenant_id, body.itemcard)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/conciliation/sbn", response_model=OkPayload)
def conciliation_sbn_store(
    body: ConciliationSbnWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    ok, msg = conc.conciliar_pair_sbn(
        db,
        tenant_id,
        body.margesi,
        body.bienes,
        body.numero_hoja,
        body.codigo_sbn,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/conciliation/desconciliacion-sbn", response_model=OkPayload)
def conciliation_desconciliacion_sbn(
    body: DesconciliarSbnWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    ok, msg = conc.desconciliar_pair_sbn(db, tenant_id, body.itemcard, body.margesi)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/conciliation/no-conciliation/no_conciliable", response_model=OkPayload)
def conciliation_mark_no_conciliable_body(
    body: NoConciliableMarkWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    ok, msg = conc.mark_no_conciliable_entity(
        db, tenant_id, body.tipo, body.id, body.observacion
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/conciliation/no-conciliation/conciliable", response_model=OkPayload)
def conciliation_mark_conciliable_body(
    body: NoConciliableMarkWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    ok, msg = conc.mark_conciliable_entity(
        db, tenant_id, body.tipo, body.id, body.observacion
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/conciliation/no-conciliable/{item_id}", response_model=OkPayload)
def conciliation_mark_no_conciliable(
    item_id: int,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    ok, msg = conc.mark_no_conciliable(db, tenant_id, item_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.delete("/conciliation/no-conciliable/{item_id}", response_model=OkPayload)
def conciliation_unmark_no_conciliable(
    item_id: int,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    ok, msg = conc.unmark_no_conciliable(db, tenant_id, item_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return OkPayload(success=True, message=msg)


@router.post("/conciliation/import", response_model=ImportConciliationResult)
def conciliation_import(
    body: ImportConciliationMatchRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    if not body.rows:
        return ImportConciliationResult(
            success=False,
            message="No hay filas para procesar",
            registrados=[],
            no_registrados=[],
        )
    result = conc.import_conciliation_match_rows(db, tenant_id, body.rows)
    return ImportConciliationResult(**result)


@router.post("/conciliation/import-desconciliar", response_model=ImportConciliationResult)
def conciliation_import_desconciliar(
    body: ImportDesconciliarRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    if body.rows:
        result = conc.import_desconciliar_match_rows(db, tenant_id, body.rows)
    elif body.item_ids:
        result = conc.import_desconciliar_rows(db, tenant_id, body.item_ids)
    else:
        return ImportConciliationResult(
            success=False,
            message="No hay filas para procesar",
            registrados=[],
            no_registrados=[],
        )
    return ImportConciliationResult(**result)


@router.post("/conciliation/sbn/import", response_model=ImportConciliationResult)
def conciliation_sbn_import(
    body: ImportConciliationMatchRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    if not body.rows:
        return ImportConciliationResult(
            success=False,
            message="No hay filas para procesar",
            registrados=[],
            no_registrados=[],
        )
    result = conc.import_conciliation_sbn_match_rows(db, tenant_id, body.rows)
    return ImportConciliationResult(**result)


@router.post("/conciliation/no-conciliation/import", response_model=ImportConciliationResult)
def conciliation_no_conciliation_import(
    body: ImportNoConciliableMatchRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    rows = [
        (r.codigo_interno, r.inv_num, r.observacion)
        for r in body.rows
    ]
    result = conc.import_no_conciliable_rows(db, tenant_id, rows)
    return ImportConciliationResult(**result)


@router.post("/conciliation/import-report/pdf")
def conciliation_import_report_pdf(
    body: ConciliationImportReportRequest,
    _: User = Depends(get_current_user),
):
    """Genera PDF con filas procesadas y errores de una importación masiva."""
    try:
        pdf_bytes, filename = conc_import_pdf.build_conciliation_import_report_pdf(
            title=body.title,
            message=body.message,
            registrados=body.registrados,
            no_registrados=body.no_registrados,
            include_sbn_column=body.include_sbn_column,
            include_ord_column=body.include_ord_column,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Error al generar PDF: {exc}") from exc
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --- Metadatos de columnas (como `columns()` en Laravel) ---


@router.get("/meta/columns/ambientes")
def meta_columns_ambientes():
    return {"code": "Código", "description": "Ambiente", "floor": "Piso", "local": "Local"}


@router.get("/meta/columns/bienes")
def meta_columns_bienes():
    return {"inv_num": "Número de Inventario", "mar_cpat": "Código SBN", "num_card": "Número de Hoja"}


@router.get("/meta/columns/cards")
def meta_columns_cards():
    return {"hoj_num": "Número", "hoj_fec": "Fecha de emisión"}
