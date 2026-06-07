from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel


class DashboardKpis(BaseModel):
    messages_sent: int
    messages_delivered: int
    messages_failed: int
    messages_read: int
    responses_received: int
    active_campaigns: int
    estimated_cost: float
    read_rate: float


class CampaignsByStatusItem(BaseModel):
    status: str
    count: int


class MessagesTimeseriesItem(BaseModel):
    label: str
    sent: int
    delivered: int


class DashboardResponse(BaseModel):
    kpis: DashboardKpis
    campaigns_by_status: list[CampaignsByStatusItem]
    messages_timeseries: list[MessagesTimeseriesItem]


class CampaignReportRow(BaseModel):
    campaign_id: UUID
    campaign_name: str
    segment_name: str | None
    sent_at: datetime | None
    sent_count: int
    delivered_count: int
    failed_count: int
    read_count: int
    response_count: int
    estimated_cost: float


class CampaignReportFilters(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    campaign_id: UUID | None = None
    segment_id: UUID | None = None
    status: str | None = None
    created_by_user_id: UUID | None = None
