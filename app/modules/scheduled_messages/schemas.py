from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ScheduledMessageCreate(BaseModel):
    campaign_id: UUID
    scheduled_date: date
    scheduled_time: time
    display_name: str | None = Field(default=None, max_length=200)
    template_id: UUID | None = None
    contenido_final: str | None = None
    segment_ids: list[UUID] | None = None


class ScheduledMessageUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    contenido_final: str | None = None
    template_id: UUID | None = None
    scheduled_date: date | None = None
    scheduled_time: time | None = None
    status: str | None = Field(default=None, max_length=40)
    segment_ids: list[UUID] | None = None
    contact_ids: list[UUID] | None = None


class ScheduledMessageOut(BaseModel):
    id: UUID
    tenant_id: UUID
    campaign_id: UUID
    display_name: str | None
    campaign_name: str
    campaign_type: str
    campaign_description: str
    template_id: UUID | None
    template_name: str | None
    contenido_final: str | None
    scheduled_date: date | None
    scheduled_time: time | None
    status: str
    segment_ids: list[UUID]
    segment_names: list[str]
    contacts_count: int
    created_at: datetime
    created_by_user_id: UUID | None
    created_by_name: str | None

    model_config = ConfigDict(from_attributes=True)


class ScheduledMessageSchedule(BaseModel):
    scheduled_date: date
    scheduled_time: time
