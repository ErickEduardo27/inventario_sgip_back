"""Resolución centralizada de tenant (cabeceras + subdominio en Host)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.tenant_host import extract_tenant_slug_from_host, parse_base_domains
from app.modules.tenants.models import Tenant

ResolvedSource = Literal["header_id", "header_slug", "host_subdomain", "default"]


def effective_request_host(host: str | None, x_forwarded_host: str | None) -> str | None:
    """Host «visible» del cliente: proxy suele mandar `X-Forwarded-Host`."""
    eff = (x_forwarded_host or "").strip().split(",")[0].strip() or None
    if eff:
        return eff
    if host and str(host).strip():
        return str(host).strip()
    return None


def resolve_tenant(
    db: Session,
    *,
    host: str | None,
    x_forwarded_host: str | None = None,
    x_tenant_id: str | None,
    x_tenant_slug: str | None,
    settings: Settings | None = None,
) -> tuple[Tenant, ResolvedSource]:
    """Devuelve el `Tenant` activo y la fuente usada. Lanza `ValueError` con mensaje para HTTP 4xx/503."""
    cfg = settings or get_settings()
    bases = parse_base_domains(cfg.tenant_base_domains)

    effective_host = effective_request_host(host, x_forwarded_host)

    if x_tenant_id:
        try:
            tid = UUID(x_tenant_id.strip())
        except ValueError as e:
            raise ValueError("X-Tenant-ID inválido") from e
        row = db.scalar(select(Tenant).where(Tenant.id == tid))
        if not row:
            raise ValueError(
                "Tenant no encontrado: el id en X-Tenant-ID no existe o quedó obsoleto. "
                "Borra el almacenamiento del sitio o vuelve a abrir el login para refrescar el tenant."
            )
        if row.status != "active":
            raise ValueError("Tenant no disponible")
        return row, "header_id"

    if x_tenant_slug:
        s = x_tenant_slug.strip().lower()
        row = db.scalar(select(Tenant).where(Tenant.slug == s))
        if not row:
            raise ValueError("Tenant no encontrado")
        if row.status != "active":
            raise ValueError("Tenant no disponible")
        return row, "header_slug"

    slug_from_host = extract_tenant_slug_from_host(effective_host, bases)
    if slug_from_host:
        row = db.scalar(select(Tenant).where(Tenant.slug == slug_from_host))
        if row and row.status == "active":
            return row, "host_subdomain"
        if cfg.tenant_subdomain_strict:
            raise ValueError(
                f"No hay tenant activo para el subdominio «{slug_from_host}». "
                "Crea el tenant con ese slug o ajusta TENANT_SUBDOMAIN_STRICT=false en desarrollo."
            )

    row = db.scalar(select(Tenant).where(Tenant.slug == cfg.default_tenant_slug))
    if not row:
        raise ValueError("No hay tenant configurado. Ejecuta migraciones y seed (slug por defecto).")
    return row, "default"
