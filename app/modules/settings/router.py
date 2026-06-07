from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_id
from app.db.session import get_db
from app.modules.iam.models import User
from app.modules.settings.schemas import SettingsOut, SettingsUpdate
from app.modules.settings.service import SettingsService

router = APIRouter()


@router.get("", response_model=SettingsOut)
def get_settings(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return SettingsService(db).get_settings(tenant_id)


@router.put("", response_model=SettingsOut)
def update_settings(
    body: SettingsUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return SettingsService(db).update_settings(tenant_id, body)
