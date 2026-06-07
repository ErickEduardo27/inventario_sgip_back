from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CatalogItemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class CatalogItemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)


class CatalogItemOut(BaseModel):
    id: UUID
    tenant_id: UUID
    name: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
