from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_tenant_id
from app.db.session import get_db
from app.modules.iam.dependencies import require_permission
from app.modules.iam.models import User
from app.modules.settings.schemas import SettingsOut, SettingsUpdate
from app.modules.settings.service import SettingsService

router = APIRouter()


@router.get("", response_model=SettingsOut)
def get_settings(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("settings", "view")),
):
    return SettingsService(db).get_settings(tenant_id)


@router.put("", response_model=SettingsOut)
def update_settings(
    body: SettingsUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("settings", "edit")),
):
    return SettingsService(db).update_settings(tenant_id, body)


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
