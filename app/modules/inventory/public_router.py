"""Rutas públicas de inventario (sin JWT), p. ej. miniatura de local."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
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
