from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_id
from app.core.exceptions import AppError
from app.db.session import get_db
from app.modules.iam.models import User
from app.modules.templates.schemas import (
    MetaWabaTemplateRow,
    TemplateCreate,
    TemplateOut,
    TemplateSubmitMetaBody,
    TemplateUpdate,
)
from app.modules.templates.service import TemplateService

router = APIRouter()


def _handle(err: AppError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.message)


@router.get("", response_model=list[TemplateOut])
def list_templates(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return TemplateService(db).list_templates(tenant_id)


@router.get("/meta/list", response_model=list[MetaWabaTemplateRow])
def list_meta_waba_templates(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Plantillas registradas en la WABA de Meta (Graph), con estado de revisión."""
    try:
        return TemplateService(db).list_meta_waba_templates()
    except AppError as e:
        raise _handle(e) from e


@router.get("/{template_id}", response_model=TemplateOut)
def get_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return TemplateService(db).get_template(tenant_id, template_id)
    except AppError as e:
        raise _handle(e) from e


@router.post("", response_model=TemplateOut, status_code=201)
def create_template(
    body: TemplateCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return TemplateService(db).create_template(tenant_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.put("/{template_id}", response_model=TemplateOut)
def update_template(
    template_id: UUID,
    body: TemplateUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return TemplateService(db).update_template(tenant_id, template_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.delete("/{template_id}", status_code=204)
def delete_template(
    template_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        TemplateService(db).delete_template(tenant_id, template_id)
    except AppError as e:
        raise _handle(e) from e


@router.post("/{template_id}/submit-to-meta", response_model=TemplateOut)
def submit_template_to_meta(
    template_id: UUID,
    body: TemplateSubmitMetaBody,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return TemplateService(db).submit_to_meta(
            tenant_id,
            template_id,
            meta_category=body.meta_category,
            language=body.language,
        )
    except AppError as e:
        raise _handle(e) from e
