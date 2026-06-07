"""Endpoints públicos para alinear el front con el tenant (subdominio / cabeceras)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.api.tenant_resolution import effective_request_host, resolve_tenant
from app.core.config import get_settings
from app.core.tenant_host import extract_tenant_slug_from_host, parse_base_domains
from app.db.session import get_db
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


@router.get("/context", response_model=TenantContextOut)
def tenant_context(
    db: Session = Depends(get_db),
    host: Annotated[str | None, Header(alias="Host")] = None,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    x_tenant_slug: Annotated[str | None, Header(alias="X-Tenant-Slug")] = None,
):
    """Devuelve el tenant que usaría el mismo criterio que `get_tenant_id` (login, inventario, etc.).

    El front puede llamar esto al cargar (con `Host` o `X-Forwarded-Host` = `window.location.host`)
    para guardar `tenant.id` y enviarlo luego como `X-Tenant-ID` si lo prefiere explícito.
    """
    settings = get_settings()
    eff = effective_request_host(host, x_forwarded_host)
    bases = parse_base_domains(settings.tenant_base_domains)
    inferred = extract_tenant_slug_from_host(eff, bases)

    try:
        row, src = resolve_tenant(
            db,
            host=host,
            x_forwarded_host=x_forwarded_host,
            x_tenant_id=x_tenant_id,
            x_tenant_slug=x_tenant_slug,
            settings=settings,
        )
    except ValueError as e:
        raise _http_from_resolve_error(str(e)) from e

    return TenantContextOut(
        tenant=TenantPublicOut.model_validate(row),
        resolved_from=src,
        effective_host=eff,
        inferred_subdomain_slug=inferred,
    )
