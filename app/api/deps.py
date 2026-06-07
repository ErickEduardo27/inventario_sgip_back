from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.tenant_resolution import resolve_tenant
from app.core.jwt import TokenError, decode_access_token
from app.db.session import get_db
from app.modules.iam.models import User


def get_tenant_id(
    db: Session = Depends(get_db),
    host: Annotated[str | None, Header(alias="Host")] = None,
    x_forwarded_host: Annotated[str | None, Header(alias="X-Forwarded-Host")] = None,
    x_tenant_id: Annotated[str | None, Header(alias="X-Tenant-ID")] = None,
    x_tenant_slug: Annotated[str | None, Header(alias="X-Tenant-Slug")] = None,
) -> UUID:
    """Resuelve el tenant en orden: `X-Tenant-ID`, `X-Tenant-Slug`, subdominio en `Host`, slug por defecto.

    Subdominio: con `TENANT_BASE_DOMAINS=localhost`, un front en `https://mi-empresa.localhost:5173`
    envía `Host: mi-empresa.localhost:5173` → slug `mi-empresa` (debe existir `tenants.slug`).

    Si el API está en otro host (p. ej. `localhost:8000`), envía `X-Forwarded-Host: mi-empresa.localhost:5173`
    (o configura el proxy para reenviarlo) para conservar el subdominio del navegador.
    """
    try:
        row, _src = resolve_tenant(
            db,
            host=host,
            x_forwarded_host=x_forwarded_host,
            x_tenant_id=x_tenant_id,
            x_tenant_slug=x_tenant_slug,
        )
    except ValueError as e:
        msg = str(e)
        if "inválido" in msg or "no existe" in msg or "obsoleto" in msg:
            raise HTTPException(status_code=400, detail=msg) from e
        if "No hay tenant configurado" in msg:
            raise HTTPException(status_code=503, detail=msg) from e
        if "subdominio" in msg:
            raise HTTPException(status_code=404, detail=msg) from e
        if "no encontrado" in msg.lower():
            raise HTTPException(status_code=404, detail=msg) from e
        if "no disponible" in msg.lower():
            raise HTTPException(status_code=403, detail=msg) from e
        raise HTTPException(status_code=400, detail=msg) from e
    return row.id


def get_current_user(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> User:
    """Resuelve al usuario autenticado desde `Authorization: Bearer <jwt>`.

    Además verifica que el `tenant_id` del token coincida con el resuelto por host/header,
    evitando que un token emitido para otro tenant se reutilice.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="No autenticado")
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    try:
        user_id = UUID(payload.get("sub", ""))
        token_tenant = UUID(payload.get("tid", ""))
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=401, detail="Token inválido") from e

    if token_tenant != tenant_id:
        raise HTTPException(status_code=401, detail="Token no corresponde a este tenant")

    user = db.scalar(
        select(User).where(
            User.id == user_id,
            User.tenant_id == tenant_id,
            User.is_deleted.is_(False),
        )
    )
    if not user:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    if user.status != "active":
        raise HTTPException(status_code=403, detail="Usuario no activo")
    return user
