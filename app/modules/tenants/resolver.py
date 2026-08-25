"""TenantResolver: obtiene el tenant activo por cabecera o subdominio."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.tenant_resolution import ResolvedSource, resolve_tenant
from app.core.config import Settings, get_settings
from app.modules.tenants.models import Tenant


class TenantResolver:
    """Resuelve el tenant de la petición.

    Prioridad: `X-Tenant-ID` → `X-Tenant-Slug` → subdominio en Host / X-Forwarded-Host
    → `DEFAULT_TENANT_SLUG`.
    """

    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def resolve(
        self,
        *,
        host: str | None,
        x_forwarded_host: str | None = None,
        x_tenant_id: str | None = None,
        x_tenant_slug: str | None = None,
    ) -> tuple[Tenant, ResolvedSource]:
        return resolve_tenant(
            self.db,
            host=host,
            x_forwarded_host=x_forwarded_host,
            x_tenant_id=x_tenant_id,
            x_tenant_slug=x_tenant_slug,
            settings=self.settings,
        )
