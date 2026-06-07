from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CampaignBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    campaign_type: str = Field(default="comunicado", max_length=60)
    start_date: date | None = None
    end_date: date | None = None
    observation: str | None = None
    segment_ids: list[UUID] = Field(default_factory=list)
    template_ids: list[UUID] = Field(default_factory=list)


class CampaignCreate(CampaignBase):
    status: str = Field(default="activo", max_length=40)

    @field_validator("status")
    @classmethod
    def validate_campaign_status(cls, v: str) -> str:
        if v not in ("activo", "inactivo"):
            raise ValueError("El estado de la campaña debe ser activo o inactivo")
        return v


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    campaign_type: str | None = Field(default=None, max_length=60)
    start_date: date | None = None
    end_date: date | None = None
    observation: str | None = None
    segment_ids: list[UUID] | None = None
    template_ids: list[UUID] | None = None
    status: str | None = Field(default=None, max_length=40)

    @field_validator("status")
    @classmethod
    def validate_campaign_status(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v not in ("activo", "inactivo"):
            raise ValueError("El estado de la campaña debe ser activo o inactivo")
        return v


class CampaignOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str
    campaign_type: str
    status: str
    start_date: date | None
    end_date: date | None
    observation: str | None

    segment_ids: list[UUID]
    segment_names: list[str]
    template_ids: list[UUID]
    template_names: list[str]

    next_scheduled_date: date | None
    next_scheduled_time: time | None

    contacts_count: int
    sent_count: int
    delivered_count: int
    failed_count: int
    read_count: int
    response_count: int
    estimated_cost: float

    sent_at: datetime | None
    finished_at: datetime | None
    created_at: datetime
    created_by_user_id: UUID | None
    created_by_name: str | None

    model_config = ConfigDict(from_attributes=True)


class CampaignSchedule(BaseModel):
    scheduled_date: date
    scheduled_time: time
