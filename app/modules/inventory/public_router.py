"""Rutas públicas de inventario (sin JWT), p. ej. miniatura de local."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from app.core.reporte_local_storage import read_local_reporte_local_file
from app.core.item_photo_storage import read_local_item_photo
from app.core.tenant_logo_storage import read_stored_logo_file, read_tenant_logo_bytes
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.inventory import models as m
from app.modules.settings.models import WorkspaceSettings

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


@router.get("/tenant-logo/{tenant_id}")
def serve_tenant_logo_current(
    tenant_id: UUID,
    kind: str = Query("portal"),
    db: Session = Depends(get_db),
) -> Response:
    """Sirve el logo del tenant (portal o PDF) desde disco o GCS privado."""
    k = (kind or "portal").strip().lower()
    if k not in ("portal", "pdf"):
        raise HTTPException(status_code=400, detail="kind debe ser portal o pdf")
    row = db.scalar(select(WorkspaceSettings).where(WorkspaceSettings.tenant_id == tenant_id))
    stored = (row.pdf_logo_url if k == "pdf" else row.logo_url) if row else None
    body = read_tenant_logo_bytes(stored, tenant_id)
    if not body:
        raise HTTPException(status_code=404, detail="Logo no encontrado")
    mime = "image/jpeg" if body[:3] == b"\xff\xd8\xff" else "image/png"
    return Response(
        content=body,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=60"},
    )


@router.get("/tenant-logo/{tenant_id}/{filename}")
def serve_tenant_logo(tenant_id: UUID, filename: str) -> Response:
    pack = read_stored_logo_file(tenant_id, filename)
    if not pack:
        raise HTTPException(status_code=404, detail="Logo no encontrado")
    body, mime = pack
    return Response(
        content=body,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/reporte-local/{kind}/{tenant_id}/{filename}")
def serve_reporte_local_file(tenant_id: UUID, kind: str, filename: str) -> Response:
    if kind not in ("foto", "pdf"):
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    pack = read_local_reporte_local_file(tenant_id, kind, filename)
    if not pack:
        raise HTTPException(status_code=404, detail="Archivo no encontrado")
    body, mime = pack
    return Response(
        content=body,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=86400"},
    )
