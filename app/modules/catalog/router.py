from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_id
from app.core.exceptions import AppError
from app.db.session import get_db
from app.modules.catalog.schemas import CatalogItemCreate, CatalogItemOut, CatalogItemUpdate
from app.modules.catalog.service import CatalogService
from app.modules.iam.models import User

router = APIRouter()


def _handle(err: AppError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.message)


# --- Sites ---


@router.get("/sites", response_model=list[CatalogItemOut])
def list_sites(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return CatalogService(db).list_sites(tenant_id)


@router.post("/sites", response_model=CatalogItemOut, status_code=201)
def create_site(
    body: CatalogItemCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return CatalogService(db).create_site(tenant_id, body.name)
    except AppError as e:
        raise _handle(e) from e


@router.put("/sites/{site_id}", response_model=CatalogItemOut)
def update_site(
    site_id: UUID,
    body: CatalogItemUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    if not body.name:
        raise HTTPException(status_code=422, detail="Nombre requerido")
    try:
        return CatalogService(db).update_site(tenant_id, site_id, body.name)
    except AppError as e:
        raise _handle(e) from e


@router.delete("/sites/{site_id}", status_code=204)
def delete_site(
    site_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        CatalogService(db).delete_site(tenant_id, site_id)
    except AppError as e:
        raise _handle(e) from e


# --- Areas ---


@router.get("/areas", response_model=list[CatalogItemOut])
def list_areas(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return CatalogService(db).list_areas(tenant_id)


@router.post("/areas", response_model=CatalogItemOut, status_code=201)
def create_area(
    body: CatalogItemCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return CatalogService(db).create_area(tenant_id, body.name)
    except AppError as e:
        raise _handle(e) from e


@router.put("/areas/{area_id}", response_model=CatalogItemOut)
def update_area(
    area_id: UUID,
    body: CatalogItemUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    if not body.name:
        raise HTTPException(status_code=422, detail="Nombre requerido")
    try:
        return CatalogService(db).update_area(tenant_id, area_id, body.name)
    except AppError as e:
        raise _handle(e) from e


@router.delete("/areas/{area_id}", status_code=204)
def delete_area(
    area_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        CatalogService(db).delete_area(tenant_id, area_id)
    except AppError as e:
        raise _handle(e) from e


# --- Positions ---


@router.get("/positions", response_model=list[CatalogItemOut])
def list_positions(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return CatalogService(db).list_positions(tenant_id)


@router.post("/positions", response_model=CatalogItemOut, status_code=201)
def create_position(
    body: CatalogItemCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return CatalogService(db).create_position(tenant_id, body.name)
    except AppError as e:
        raise _handle(e) from e


@router.put("/positions/{position_id}", response_model=CatalogItemOut)
def update_position(
    position_id: UUID,
    body: CatalogItemUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    if not body.name:
        raise HTTPException(status_code=422, detail="Nombre requerido")
    try:
        return CatalogService(db).update_position(tenant_id, position_id, body.name)
    except AppError as e:
        raise _handle(e) from e


@router.delete("/positions/{position_id}", status_code=204)
def delete_position(
    position_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        CatalogService(db).delete_position(tenant_id, position_id)
    except AppError as e:
        raise _handle(e) from e
