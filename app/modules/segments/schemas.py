from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SegmentCriteria(BaseModel):
    site_ids: list[UUID] = Field(default_factory=list)
    area_ids: list[UUID] = Field(default_factory=list)
    position_ids: list[UUID] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    created_from: str | None = None


class SegmentBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    criteria: SegmentCriteria = Field(default_factory=SegmentCriteria)
    status: str = Field(default="activo", max_length=40)


class SegmentCreate(SegmentBase):
    pass


class SegmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=500)
    criteria: SegmentCriteria | None = None
    status: str | None = Field(default=None, max_length=40)


class SegmentOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    description: str
    criteria: dict[str, Any]
    status: str
    contact_count: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class SegmentPreview(BaseModel):
    contact_count: int
