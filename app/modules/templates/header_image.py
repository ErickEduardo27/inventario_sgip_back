"""Decodificación y validación de imagen de cabecera para plantillas Meta."""

from __future__ import annotations

import base64
import binascii
from typing import Final

from app.core.exceptions import AppError

_MAX_BYTES: Final[int] = 2 * 1024 * 1024
_ALLOWED_MIME: Final[set[str]] = {"image/jpeg", "image/png", "image/webp"}


def decode_template_header_upload(b64_or_data_url: str, mime_hint: str | None) -> tuple[bytes, str]:
    s = (b64_or_data_url or "").strip()
    if not s:
        raise AppError("La imagen de cabecera está vacía.", 400)

    mime = (mime_hint or "").strip().split(";")[0].strip() or "application/octet-stream"
    if s.startswith("data:"):
        meta, _, b64 = s.partition(",")
        mime = meta.replace("data:", "").split(";")[0].strip() or mime
        try:
            raw = base64.b64decode(b64, validate=True)
        except binascii.Error as e:
            raise AppError("Imagen en base64 inválida.", 400) from e
    else:
        try:
            raw = base64.b64decode(s, validate=True)
        except binascii.Error as e:
            raise AppError("Imagen en base64 inválida.", 400) from e

    if len(raw) > _MAX_BYTES:
        raise AppError(f"La imagen supera {_MAX_BYTES // (1024 * 1024)} MB.", 400)

    if mime not in _ALLOWED_MIME:
        if raw[:3] == b"\xff\xd8\xff":
            mime = "image/jpeg"
        elif raw[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"
        elif len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
            mime = "image/webp"
        else:
            raise AppError("Formato no admitido: usa JPEG, PNG o WebP.", 400)

    return raw, mime
