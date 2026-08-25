"""Contrato público de TenantConfig (tema + flags + slots)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.modules.tenants.theme import TenantThemeOut


class TenantConfigTenant(BaseModel):
    id: UUID
    slug: str
    name: str
    status: str
    locale: str
    timezone: str
    currency: str
    plan_code: str

    model_config = ConfigDict(from_attributes=True)


class FeatureCatalogItem(BaseModel):
    code: str
    name: str
    group: str
    locked: bool = False


class ComponentSlotCatalogItem(BaseModel):
    slot: str
    label: str
    variants: list[str] = Field(default_factory=list)


class TenantConfigOut(BaseModel):
    """Configuración completa del tenant para arrancar el front (público, pre-login)."""

    tenant: TenantConfigTenant
    resolved_from: Literal["header_id", "header_slug", "host_subdomain", "default"]
    effective_host: str | None = None
    inferred_subdomain_slug: str | None = None
    theme: TenantThemeOut
    features: dict[str, bool]
    feature_catalog: list[FeatureCatalogItem]
    custom_components: dict[str, str]
    component_slots: list[ComponentSlotCatalogItem]
