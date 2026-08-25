from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TenantNameUpdate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class TenantPublicOut(BaseModel):
    """Datos mínimos para que el front resuelva X-Tenant-ID (público)."""

    id: UUID
    slug: str
    name: str
    status: str

    model_config = ConfigDict(from_attributes=True)


class TenantContextOut(BaseModel):
    """Contexto del tenant según la petición (subdominio / cabeceras). Público, sin JWT."""

    tenant: TenantPublicOut
    resolved_from: Literal["header_id", "header_slug", "host_subdomain", "default"]
    """Origen de la resolución del tenant."""
    effective_host: str | None = None
    """Host usado para inferir subdominio (tras `X-Forwarded-Host` si existe)."""
    inferred_subdomain_slug: str | None = None
    """Slug parseado del host; puede existir aunque `resolved_from` sea otra (p. ej. cabecera prioritaria)."""

    model_config = ConfigDict(from_attributes=True)
