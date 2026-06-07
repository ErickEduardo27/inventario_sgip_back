from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_id
from app.core.exceptions import AppError
from app.db.session import get_db
from app.modules.campaigns.schemas import (
    CampaignCreate,
    CampaignOut,
    CampaignSchedule,
    CampaignUpdate,
)
from app.modules.campaigns.service import CampaignService
from app.modules.iam.models import User

router = APIRouter()


def _handle(err: AppError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.message)


@router.get("", response_model=list[CampaignOut])
def list_campaigns(
    statuses: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return CampaignService(db).list_campaigns(tenant_id, statuses=statuses)


@router.get("/{campaign_id}", response_model=CampaignOut)
def get_campaign(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return CampaignService(db).get_campaign_out(tenant_id, campaign_id)
    except AppError as e:
        raise _handle(e) from e


@router.post("", response_model=CampaignOut, status_code=201)
def create_campaign(
    body: CampaignCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        return CampaignService(db).create_campaign(tenant_id, user.id, body)
    except AppError as e:
        raise _handle(e) from e


@router.put("/{campaign_id}", response_model=CampaignOut)
def update_campaign(
    campaign_id: UUID,
    body: CampaignUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return CampaignService(db).update_campaign(tenant_id, campaign_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        CampaignService(db).delete_campaign(tenant_id, campaign_id)
    except AppError as e:
        raise _handle(e) from e


@router.post("/{campaign_id}/duplicate", response_model=CampaignOut, status_code=201)
def duplicate_campaign(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        return CampaignService(db).duplicate_campaign(tenant_id, campaign_id, user.id)
    except AppError as e:
        raise _handle(e) from e


@router.post("/{campaign_id}/schedule", response_model=CampaignOut)
def schedule_campaign(
    campaign_id: UUID,
    body: CampaignSchedule,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        return CampaignService(db).schedule_campaign(tenant_id, campaign_id, body, user.id)
    except AppError as e:
        raise _handle(e) from e


@router.post("/{campaign_id}/cancel", response_model=CampaignOut)
def cancel_campaign(
    campaign_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return CampaignService(db).cancel_campaign(tenant_id, campaign_id)
    except AppError as e:
        raise _handle(e) from e
