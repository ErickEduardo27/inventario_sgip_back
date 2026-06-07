from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_id
from app.db.session import get_db
from app.modules.iam.models import User
from app.modules.reports.schemas import (
    CampaignReportFilters,
    CampaignReportRow,
    DashboardResponse,
)
from app.modules.reports.service import ReportsService

router = APIRouter()


@router.get("/dashboard", response_model=DashboardResponse)
def dashboard(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    campaign_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return ReportsService(db).dashboard(
        tenant_id, date_from=date_from, date_to=date_to, campaign_id=campaign_id
    )


@router.get("/campaigns", response_model=list[CampaignReportRow])
def campaigns_report(
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    campaign_id: UUID | None = Query(default=None),
    segment_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    created_by_user_id: UUID | None = Query(default=None),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    filters = CampaignReportFilters(
        date_from=date_from,
        date_to=date_to,
        campaign_id=campaign_id,
        segment_id=segment_id,
        status=status,
        created_by_user_id=created_by_user_id,
    )
    return ReportsService(db).campaigns_report(tenant_id, filters)
