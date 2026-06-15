"""Rutas públicas de inventario (sin JWT), p. ej. miniatura de local."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from app.core.item_photo_storage import read_local_item_photo
from app.core.tenant_logo_storage import read_local_tenant_logo
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.inventory import models as m

router = APIRouter()


@router.get("/establishment-photo/{token}")
def serve_establishment_photo(token: UUID, db: Session = Depends(get_db)) -> Response:
    row = db.scalar(select(m.InvEstablishment).where(m.InvEstablishment.photo_token == token))
    if not row or not row.photo_blob:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    mime = (row.photo_mime or "image/jpeg").split(";")[0].strip() or "image/jpeg"
    blob = row.photo_blob
    body = bytes(blob) if not isinstance(blob, (bytes, bytearray)) else bytes(blob)
    return Response(
        content=body,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/item-photo/{tenant_id}/{filename}")
def serve_item_photo(tenant_id: UUID, filename: str) -> Response:
    pack = read_local_item_photo(tenant_id, filename)
    if not pack:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    body, mime = pack
    return Response(
        content=body,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/tenant-logo/{tenant_id}/{filename}")
def serve_tenant_logo(tenant_id: UUID, filename: str) -> Response:
    pack = read_local_tenant_logo(tenant_id, filename)
    if not pack:
        raise HTTPException(status_code=404, detail="Logo no encontrado")
    body, mime = pack
    return Response(
        content=body,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=3600"},
    )
