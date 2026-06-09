"""API REST de inventario (equivalente a rutas tenant del monolito Laravel)."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_tenant_id
from app.modules.iam.dependencies import require_permission
from app.modules.iam.models import User
from app.modules.inventory import conciliation as conc
from app.modules.inventory import cost_center_import as cc_import
from app.modules.inventory import list_sbn_import as list_sbn_import_mod
from app.modules.inventory import margesi_import as margesi_import_mod
from app.modules.inventory import person_import as person_import_mod
from app.modules.inventory import environment_import as env_import
from app.modules.inventory import establishment_import as est_import
from app.modules.inventory import cards_import as cards_import_mod
from app.modules.inventory import hoja_captura_import as hoja_captura_import_mod
from app.modules.inventory import import_common as imp_common
from app.modules.inventory import geo_catalog as geo
from app.modules.inventory import models as inv_models
from app.modules.inventory import service as inv
from app.modules.inventory.csv_export import csv_download_response
from app.modules.inventory.export_queries import get_export_query
from app.modules.inventory.schemas import (
    CardItemWrite,
    CardWrite,
    ConciliationFilters,
    ConciliationPairWrite,
    ConciliationSbnWrite,
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
    ImportConciliationMatchRequest,
    ImportConciliationResult,
    ImportConciliationRow,
    ImportDesconciliarRequest,
    ImportNoConciliableMatchRequest,
    NoConciliableMarkWrite,
    InventoryDashboardResponse,
    InventoryNumWrite,
    ItemCardTablesResponse,
    ItemPhotoUploadResult,
    ItemCardTranslate,
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
    return inv.establishment_row_public_dict(row)


@router.post("/establishments", response_model=OkPayload)
def establishment_save(
    body: EstablishmentWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        inv.upsert_establishment(db, tenant_id, body)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return OkPayload(success=True, message="Establecimiento guardado")


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
    return inv.row_to_dict(row)


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
    return inv.row_to_dict(row)


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
    return inv.row_to_dict(row)


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


router.add_api_route(
    "/hoja-captura/export",
    _csv_export_route("cards", "hoja_captura"),
    methods=["GET"],
    tags=["inventory"],
)


@router.get("/cards/{row_id}")
def card_get(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id)):
    from app.modules.inventory import models as m

    row = db.get(m.InvCard, row_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="No encontrado")
    return inv.row_to_dict(row)


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


@router.get("/item-cards/records", response_model=PagedRows)
def item_cards_records(
    db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id), q: RecordQuery = Depends(_q)
):
    allowed = {"inv_num", "mar_cpat", "mar_num", "mar_des", "inv_sit", "id_card"}
    rows, total = inv.list_item_cards(db, tenant_id, q, allowed | {"num_card"})
    return PagedRows(data=rows, meta=PagedMeta(**inv.paged_meta(total, q.page, q.per_page)))


@router.get(
    "/item-cards/export",
    _csv_export_route("item_cards", "bienes"),
)


@router.get("/item-cards/{row_id}")
def item_card_get(row_id: int, db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id)):
    from app.modules.inventory import models as m

    row = db.get(m.InvItemCard, row_id)
    if not row or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="No encontrado")
    return inv.row_to_dict(row)


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
    _: User = Depends(get_current_user),
):
    ok, msg = inv.delete_item_card(db, tenant_id, item_id, id_card)
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
    return inv.row_to_dict(row)


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


router.add_api_route(
    "/margesi/export",
    _csv_export_route("margesi", "margesi"),
    methods=["GET"],
    tags=["inventory"],
)


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
    pairs: list[ImportConciliationRow] = []
    for row in body.rows:
        margesi_id, bien_id, reason = conc.match_import_conciliation(
            db,
            tenant_id,
            row.codigo_interno,
            row.inv_num,
            row.mar_cpat,
        )
        if margesi_id and bien_id and not reason:
            inv_con = (row.ord_conciliacion or "").strip() or "1"
            pairs.append(
                ImportConciliationRow(
                    margesi_id=margesi_id,
                    bien_id=bien_id,
                    inv_con=inv_con,
                )
            )
    if not pairs:
        return ImportConciliationResult(
            success=False,
            message="No se encontraron pares válidos para conciliar",
            registrados=[],
            no_registrados=[r.model_dump() for r in body.rows],
        )
    result = conc.import_conciliar_rows(db, tenant_id, pairs)
    return ImportConciliationResult(**result)


@router.post("/conciliation/import-desconciliar", response_model=ImportConciliationResult)
def conciliation_import_desconciliar(
    body: ImportDesconciliarRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    result = conc.import_desconciliar_rows(db, tenant_id, body.item_ids)
    return ImportConciliationResult(**result)


@router.post("/conciliation/sbn/import", response_model=ImportConciliationResult)
def conciliation_sbn_import(
    body: ImportConciliationMatchRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    pairs: list[ImportConciliationRow] = []
    for row in body.rows:
        margesi_id, bien_id, reason = conc.match_import_conciliation_sbn(
            db,
            tenant_id,
            row.codigo_interno,
            row.inv_num,
            row.mar_cpat,
        )
        if margesi_id and bien_id and not reason:
            pairs.append(ImportConciliationRow(margesi_id=margesi_id, bien_id=bien_id))
    if not pairs:
        return ImportConciliationResult(
            success=False,
            message="No se encontraron pares válidos para conciliación SBN",
            registrados=[],
            no_registrados=[r.model_dump() for r in body.rows],
        )
    registrados: list[dict] = []
    no_registrados: list[dict] = []
    for pair in pairs:
        marg = db.get(inv_models.InvMargesiItem, pair.margesi_id)
        bien = db.get(inv_models.InvItemCard, pair.bien_id)
        card = db.get(inv_models.InvCard, bien.id_card) if bien else None
        codigo = "".join(c for c in str(marg.mar_cpat or "") if c.isdigit()) if marg else ""
        ok, msg = conc.conciliar_pair_sbn(
            db,
            tenant_id,
            pair.margesi_id,
            pair.bien_id,
            card.hoj_num if card else "",
            codigo,
        )
        entry = {"margesi_id": pair.margesi_id, "bien_id": pair.bien_id, "message": msg}
        if ok:
            registrados.append(entry)
        else:
            no_registrados.append(entry)
    success = len(registrados) > 0
    return ImportConciliationResult(
        success=success,
        message="Importación SBN completada" if success else "No se pudo conciliar ningún registro",
        registrados=registrados,
        no_registrados=no_registrados,
    )


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
