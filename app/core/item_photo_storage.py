"""Fotos de bienes (hoja de captura): GCS en producción, disco local + URL pública en desarrollo."""

from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings

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


def _gcs_client():
    from google.cloud import storage

    settings = get_settings()
    creds = settings.google_application_credentials.strip()
    if creds:
        return storage.Client.from_service_account_json(creds)
    return storage.Client()


def _gcs_public_url(bucket: str, object_key: str) -> str:
    return f"https://storage.googleapis.com/{bucket}/{object_key}"


def _local_public_url(tenant_id: UUID, filename: str) -> str:
    settings = get_settings()
    base = (settings.public_api_base_url or "").rstrip("/")
    path = f"/api/public/item-photo/{tenant_id}/{filename}"
    return f"{base}{path}" if base else path


def upload_item_photo(*, tenant_id: UUID, inv_num: str, slot: int, content: bytes) -> str:
    """Sube bytes (JPEG comprimido en cliente) y devuelve la URL HTTPS a guardar en BD."""
    if slot not in (1, 2, 3):
        raise ValueError("Slot de foto inválido")

    settings = get_settings()
    if settings.gcs_bucket:
        object_key = build_item_photo_object_key(tenant_id=tenant_id, inv_num=inv_num, slot=slot)
        client = _gcs_client()
        blob = client.bucket(settings.gcs_bucket).blob(object_key)
        blob.upload_from_string(content, content_type=_jpeg_content_type())
        return _gcs_public_url(settings.gcs_bucket, object_key)

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


def _parse_gcs_url(url: str) -> tuple[str, str] | None:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(url.strip())
    if parsed.netloc != "storage.googleapis.com":
        return None
    path = unquote(parsed.path or "").lstrip("/")
    if not path or "/" not in path:
        return None
    bucket, key = path.split("/", 1)
    return bucket, key


def _tenant_in_object_key(tenant_id: UUID, key: str) -> bool:
    tid = str(tenant_id)
    parts = key.strip("/").split("/")
    return tid in parts


def _download_gcs_object(bucket: str, key: str) -> tuple[bytes, str] | None:
    try:
        data = _gcs_client().bucket(bucket).blob(key).download_as_bytes()
    except Exception:
        return None
    mime, _ = mimetypes.guess_type(key)
    return data, (mime or "image/jpeg").split(";")[0].strip() or "image/jpeg"


def read_item_photo_bytes(stored: str, tenant_id: UUID) -> tuple[bytes, str] | None:
    """Lee bytes de una foto referenciada en ``extra.mar_foto*`` (GCS, ruta pública local o nombre legacy)."""
    raw = (stored or "").strip()
    if not raw:
        return None

    marker = f"/api/public/item-photo/{tenant_id}/"
    if marker in raw:
        filename = raw.split(marker, 1)[-1].split("?")[0]
        return read_local_item_photo(tenant_id, filename)

    if re.fullmatch(r"[\w.-]+\.(?:jpe?g|png|webp|gif)", raw, re.I):
        return read_local_item_photo(tenant_id, raw)

    gcs = _parse_gcs_url(raw)
    if gcs:
        bucket, key = gcs
        if not _tenant_in_object_key(tenant_id, key):
            return None
        return _download_gcs_object(bucket, key)

    settings = get_settings()
    prefix = (settings.gcs_item_photos_prefix or "item-photos").strip("/") or "item-photos"
    if settings.gcs_bucket:
        key = raw.lstrip("/")
        if key.startswith(f"{prefix}/") and _tenant_in_object_key(tenant_id, key):
            return _download_gcs_object(settings.gcs_bucket, key)

    return None
