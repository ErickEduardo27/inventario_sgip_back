"""Fotos de bienes (hoja de captura): R2/GCS en producción, disco local + URL pública en desarrollo."""

from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings
from app.core import object_storage as obj

LOCAL_PREFIX = "local:"


def _safe_inv_segment(inv_num: str) -> str:
    return re.sub(r"[^\w.-]+", "_", (inv_num or "").strip()) or "sin_num"


def _jpeg_content_type() -> str:
    return "image/jpeg"


def build_item_photo_object_key(*, tenant_id: UUID, inv_num: str, slot: int) -> str:
    settings = get_settings()
    prefix = (settings.gcs_item_photos_prefix or "item-photos").strip("/") or "item-photos"
    name = f"{_safe_inv_segment(inv_num)}_{slot}_{uuid.uuid4().hex[:12]}.jpg"
    return f"{prefix}/{tenant_id}/{name}"


def _local_public_url(tenant_id: UUID, filename: str) -> str:
    settings = get_settings()
    base = (settings.public_api_base_url or "").rstrip("/")
    path = f"/api/public/item-photo/{tenant_id}/{filename}"
    return f"{base}{path}" if base else path


def upload_item_photo(*, tenant_id: UUID, inv_num: str, slot: int, content: bytes) -> str:
    """Sube bytes (JPEG comprimido en cliente) y devuelve la URL/clave a guardar en BD."""
    if slot not in (1, 2, 3):
        raise ValueError("Slot de foto inválido")

    if obj.cloud_enabled():
        object_key = build_item_photo_object_key(tenant_id=tenant_id, inv_num=inv_num, slot=slot)
        obj.upload_bytes(object_key, content, content_type=_jpeg_content_type())
        return obj.public_object_url(object_key)

    inv = _safe_inv_segment(inv_num)
    filename = f"{inv}_{slot}_{uuid.uuid4().hex[:8]}.jpg"
    base = Path(__file__).resolve().parents[2] / "uploads" / "hoja_captura" / str(tenant_id)
    base.mkdir(parents=True, exist_ok=True)
    (base / filename).write_bytes(content)
    return _local_public_url(tenant_id, filename)


def read_local_item_photo(tenant_id: UUID, filename: str) -> tuple[bytes, str] | None:
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        return None
    path = Path(__file__).resolve().parents[2] / "uploads" / "hoja_captura" / str(tenant_id) / safe
    if not path.is_file():
        return None
    mime, _ = mimetypes.guess_type(safe)
    return path.read_bytes(), (mime or "image/jpeg").split(";")[0].strip() or "image/jpeg"


def _tenant_in_object_key(tenant_id: UUID, key: str) -> bool:
    tid = str(tenant_id)
    parts = key.strip("/").split("/")
    return tid in parts


def read_item_photo_bytes(stored: str, tenant_id: UUID) -> tuple[bytes, str] | None:
    """Lee bytes de una foto referenciada en ``extra.mar_foto*`` (R2, URL GCS antigua, local o legacy)."""
    raw = (stored or "").strip()
    if not raw:
        return None

    marker = f"/api/public/item-photo/{tenant_id}/"
    if marker in raw:
        filename = raw.split(marker, 1)[-1].split("?")[0]
        return read_local_item_photo(tenant_id, filename)

    if re.fullmatch(r"[\w.-]+\.(?:jpe?g|png|webp|gif)", raw, re.I):
        return read_local_item_photo(tenant_id, raw)

    if obj.cloud_enabled():
        key = obj.parse_object_key(raw)
        if key and _tenant_in_object_key(tenant_id, key):
            data = obj.download_stored(raw)
            if data is not None:
                mime, _ = mimetypes.guess_type(key)
                return data, (mime or "image/jpeg").split(";")[0].strip() or "image/jpeg"

        settings = get_settings()
        prefix = (settings.gcs_item_photos_prefix or "item-photos").strip("/") or "item-photos"
        key = raw.lstrip("/")
        if key.startswith(f"{prefix}/") and _tenant_in_object_key(tenant_id, key):
            try:
                data = obj.download_bytes(key)
            except Exception:
                return None
            mime, _ = mimetypes.guess_type(key)
            return data, (mime or "image/jpeg").split(";")[0].strip() or "image/jpeg"

    return None
