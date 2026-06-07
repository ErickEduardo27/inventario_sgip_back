"""Rutas públicas (sin JWT) para recursos que deben ver terceros, p. ej. Meta al descargar cabeceras."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.modules.templates.models import MessageTemplate

router = APIRouter()


@router.get("/template-header-image/{token}")
def serve_template_header_image(token: UUID, db: Session = Depends(get_db)) -> Response:
    row = db.scalar(
        select(MessageTemplate).where(
            MessageTemplate.wa_header_image_token == token,
            MessageTemplate.is_deleted.is_(False),
        )
    )
    if not row or not row.wa_header_image_blob:
        raise HTTPException(status_code=404, detail="Imagen no encontrada")
    mime = (row.wa_header_image_mime or "image/jpeg").split(";")[0].strip() or "image/jpeg"
    blob = row.wa_header_image_blob
    body = bytes(blob) if not isinstance(blob, (bytes, bytearray)) else bytes(blob)
    return Response(
        content=body,
        media_type=mime,
        headers={"Cache-Control": "public, max-age=86400"},
    )
