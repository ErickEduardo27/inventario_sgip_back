"""Endpoints públicos para alinear el front con el tenant (subdominio / cabeceras)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.tenant_resolution import effective_request_host
from app.core.config import get_settings
from app.core.tenant_host import extract_tenant_slug_from_host, parse_base_domains
from app.db.session import get_db
from app.modules.tenants.config_schemas import TenantConfigOut
from app.modules.tenants.config_service import TenantConfigService
from app.modules.tenants.resolver import TenantResolver
from app.modules.tenants.schemas import TenantContextOut, TenantPublicOut

router = APIRouter()


def _http_from_resolve_error(msg: str) -> HTTPException:
    if "inválido" in msg or "no existe" in msg or "obsoleto" in msg:
        return HTTPException(status_code=400, detail=msg)
    if "No hay tenant configurado" in msg:
        return HTTPException(status_code=503, detail=msg)
    if "subdominio" in msg:
        return HTTPException(status_code=404, detail=msg)
    if "no encontrado" in msg.lower():
        return HTTPException(status_code=404, detail=msg)
    if "no disponible" in msg.lower():
        return HTTPException(status_code=403, detail=msg)
    return HTTPException(status_code=400, detail=msg)


def _resolve_row(
    db: Session,
    *,
    host: str | None,
    x_forwarded_host: str | None,
    x_tenant_id: str | None,
    x_tenant_slug: str | None,
):
    settings = get_settings()
    eff = effective_request_host(host, x_forwarded_host)
    bases = parse_base_domains(settings.tenant_base_domains)
    inferred = extract_tenant_slug_from_host(eff, bases)
    try:
        row, src = TenantResolver(db, settings).resolve(
            host=host,
            x_forwarded_host=x_forwarded_host,
            x_tenant_id=x_tenant_id,
            x_tenant_slug=x_tenant_slug,
        )
    except ValueError as e:
        raise _http_from_resolve_error(str(e)) from e
    return row, src, eff, inferred


@router.get("/context", response_model=TenantContextOut)
def tenant_context(
    db: Session = Depends(get_db),
    host: Annotated[str | None, Header(alias="Host")] = None,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    x_tenant_slug: Annotated[str | None, Header(alias="X-Tenant-Slug")] = None,
):
    """Datos mínimos del tenant (compatibilidad). Preferir `GET /api/tenant/config`."""
    row, src, eff, inferred = _resolve_row(
        db,
        host=host,
        x_forwarded_host=x_forwarded_host,
        x_tenant_id=x_tenant_id,
        x_tenant_slug=x_tenant_slug,
    )
    return TenantContextOut(
        tenant=TenantPublicOut.model_validate(row),
        resolved_from=src,
        effective_host=eff,
        inferred_subdomain_slug=inferred,
    )


@router.get("/config", response_model=TenantConfigOut)
def tenant_config(
    db: Session = Depends(get_db),
    host: Annotated[str | None, Header(alias="Host")] = None,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    x_tenant_slug: Annotated[str | None, Header(alias="X-Tenant-Slug")] = None,
):
    """Configuración completa del tenant: tema, módulos y slots de componentes."""
    row, src, eff, inferred = _resolve_row(
        db,
        host=host,
        x_forwarded_host=x_forwarded_host,
        x_tenant_id=x_tenant_id,
        x_tenant_slug=x_tenant_slug,
    )
    return TenantConfigService(db).build(
        row,
        resolved_from=src,
        effective_host=eff,
        inferred_subdomain_slug=inferred,
    )
