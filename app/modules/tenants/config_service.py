"""Ensambla TenantConfig a partir del tenant resuelto + workspace_settings."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.tenant_resolution import ResolvedSource
from app.modules.settings.service import SettingsService
from app.modules.tenants.component_slots import COMPONENT_SLOTS, merge_custom_components
from app.modules.tenants.config_schemas import (
    ComponentSlotCatalogItem,
    FeatureCatalogItem,
    TenantConfigOut,
    TenantConfigTenant,
)
from app.modules.tenants.features import FEATURE_CATALOG, LOCKED_FEATURES, merge_features
from app.modules.tenants.models import Tenant
from app.modules.tenants.theme import parse_theme


class TenantConfigService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def build(
        self,
        tenant: Tenant,
        *,
        resolved_from: ResolvedSource,
        effective_host: str | None,
        inferred_subdomain_slug: str | None,
    ) -> TenantConfigOut:
        settings = SettingsService(self.db).get_settings(tenant.id)
        theme = parse_theme(settings.portal_branding, logo_url=settings.logo_url)
        features = merge_features(settings.feature_flags)
        slots = merge_custom_components(settings.custom_components)

        return TenantConfigOut(
            tenant=TenantConfigTenant.model_validate(tenant),
            resolved_from=resolved_from,
            effective_host=effective_host,
            inferred_subdomain_slug=inferred_subdomain_slug,
            theme=theme,
            features=features,
            feature_catalog=[
                FeatureCatalogItem(
                    code=item["code"],
                    name=item["name"],
                    group=item["group"],
                    locked=item["code"] in LOCKED_FEATURES,
                )
                for item in FEATURE_CATALOG
            ],
            custom_components=slots,
            component_slots=[ComponentSlotCatalogItem(**item) for item in COMPONENT_SLOTS],
        )
