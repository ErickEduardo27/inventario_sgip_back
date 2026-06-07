from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_id
from app.core.exceptions import AppError
from app.db.session import get_db
from app.modules.contacts.schemas import (
    ContactCreate,
    ContactOut,
    ContactSummary,
    ContactUpdate,
)
from app.modules.contacts.service import ContactService
from app.modules.iam.models import User

router = APIRouter()


def _handle(err: AppError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.message)


@router.get("", response_model=list[ContactOut])
def list_contacts(
    search: str | None = Query(default=None),
    site_id: UUID | None = Query(default=None),
    area_id: UUID | None = Query(default=None),
    position_id: UUID | None = Query(default=None),
    region: str | None = Query(default=None),
    status: str | None = Query(default=None),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return ContactService(db).list_contacts(
        tenant_id,
        search=search,
        site_id=site_id,
        area_id=area_id,
        position_id=position_id,
        region=region,
        status=status,
    )


@router.get("/summary", response_model=ContactSummary)
def summary(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return ContactService(db).summary(tenant_id)


@router.get("/{contact_id}", response_model=ContactOut)
def get_contact(
    contact_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return ContactService(db).get_contact_out(tenant_id, contact_id)
    except AppError as e:
        raise _handle(e) from e


@router.post("", response_model=ContactOut, status_code=201)
def create_contact(
    body: ContactCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return ContactService(db).create_contact(tenant_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.put("/{contact_id}", response_model=ContactOut)
def update_contact(
    contact_id: UUID,
    body: ContactUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return ContactService(db).update_contact(tenant_id, contact_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.delete("/{contact_id}", status_code=204)
def delete_contact(
    contact_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        ContactService(db).delete_contact(tenant_id, contact_id)
    except AppError as e:
        raise _handle(e) from e
