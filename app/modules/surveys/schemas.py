from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SurveyBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1)
    response_type: str = Field(default="si_no", max_length=40)
    options: list[str] = Field(default_factory=list)
    campaign_id: UUID | None = None
    segment_id: UUID | None = None
    status: str = Field(default="activo", max_length=40)


class SurveyCreate(SurveyBase):
    pass


class SurveyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    question: str | None = Field(default=None, min_length=1)
    response_type: str | None = Field(default=None, max_length=40)
    options: list[str] | None = None
    campaign_id: UUID | None = None
    segment_id: UUID | None = None
    status: str | None = Field(default=None, max_length=40)


class SurveyOut(SurveyBase):
    id: UUID
    tenant_id: UUID
    response_count: int
    campaign_name: str | None = None
    segment_name: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
