from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_tenant_id
from app.db.session import get_db
from app.modules.iam.dependencies import require_permission
from app.modules.iam.models import User
from app.core.exceptions import AppError
from app.modules.settings.schemas import SettingsOut, SettingsUpdate
from app.modules.settings.service import SettingsService
from app.modules.tenants.schemas import TenantNameUpdate, TenantPublicOut
from app.modules.tenants.service import TenantService
from pydantic import ValidationError

router = APIRouter()


@router.get("", response_model=SettingsOut)
@router.get("/", response_model=SettingsOut, include_in_schema=False)
def read_workspace_settings(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("settings", "view")),
):
    return SettingsService(db).get_settings(tenant_id)


@router.put("", response_model=SettingsOut)
@router.put("/", response_model=SettingsOut, include_in_schema=False)
def update_settings(
    body: SettingsUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("settings", "edit")),
):
    try:
        return SettingsService(db).update_settings(tenant_id, body)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/tenant-name", response_model=TenantPublicOut)
def update_tenant_name(
    body: TenantNameUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("settings", "edit")),
):
    try:
        row = TenantService(db).update_name(tenant_id, body.name)
    except AppError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from exc
    return TenantPublicOut.model_validate(row)


@router.post("/logo", response_model=SettingsOut)
async def upload_logo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("settings", "edit")),
):
    content = await file.read()
    content_type = file.content_type or "application/octet-stream"
    try:
        return SettingsService(db).upload_logo(tenant_id, content, content_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/logo", response_model=SettingsOut)
def delete_logo(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("settings", "edit")),
):
    return SettingsService(db).clear_logo(tenant_id)


@router.post("/pdf-logo", response_model=SettingsOut)
async def upload_pdf_logo(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("settings", "edit")),
):
    content = await file.read()
    content_type = file.content_type or "application/octet-stream"
    try:
        return SettingsService(db).upload_pdf_logo(tenant_id, content, content_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/pdf-logo", response_model=SettingsOut)
def delete_pdf_logo(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("settings", "edit")),
):
    return SettingsService(db).clear_pdf_logo(tenant_id)
