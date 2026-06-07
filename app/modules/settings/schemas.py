from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SettingsBase(BaseModel):
    business_name: str = Field(default="", max_length=200)
    business_sector: str | None = Field(default=None, max_length=120)
    whatsapp_number: str | None = Field(default=None, max_length=50)
    whatsapp_display_name: str | None = Field(default=None, max_length=200)
    connection_status: str = Field(default="pendiente", max_length=40)
    cost_per_message: float = 0
    currency: str = Field(default="PEN", max_length=10)
    timezone: str = Field(default="America/Lima", max_length=80)
    logo_url: str | None = Field(default=None, max_length=500)
    google_cloud_info: dict[str, Any] = Field(default_factory=dict)
    alerts_config: dict[str, Any] = Field(default_factory=dict)
    portal_branding: dict[str, Any] = Field(default_factory=dict)
    integration_notes: str | None = None


class SettingsUpdate(BaseModel):
    business_name: str | None = Field(default=None, max_length=200)
    business_sector: str | None = Field(default=None, max_length=120)
    whatsapp_number: str | None = Field(default=None, max_length=50)
    whatsapp_display_name: str | None = Field(default=None, max_length=200)
    connection_status: str | None = Field(default=None, max_length=40)
    cost_per_message: float | None = None
    currency: str | None = Field(default=None, max_length=10)
    timezone: str | None = Field(default=None, max_length=80)
    logo_url: str | None = Field(default=None, max_length=500)
    google_cloud_info: dict[str, Any] | None = None
    alerts_config: dict[str, Any] | None = None
    portal_branding: dict[str, Any] | None = None
    integration_notes: str | None = None


class SettingsOut(SettingsBase):
    id: UUID
    tenant_id: UUID

    model_config = ConfigDict(from_attributes=True)
