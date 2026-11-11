"""Archivos de Reporte Locales (fotos y PDF): R2/GCS en producción, disco local en desarrollo."""

from __future__ import annotations

import mimetypes
import re
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from uuid import UUID

from app.core.config import get_settings
from app.core import object_storage as obj

MAX_FOTOS = 5
MAX_PDFS = 2
LOCAL_PREFIX = "local:"


def _safe_establishment_segment(establishment_id: int) -> str:
    return re.sub(r"[^\w.-]+", "_", str(establishment_id)) or "local"


def _fotos_prefix() -> str:
    settings = get_settings()
    return (settings.gcs_local_fotos_prefix or "local-fotos").strip("/") or "local-fotos"


def _pdfs_prefix() -> str:
    settings = get_settings()
    return (settings.gcs_local_pdf_prefix or "local-pdf").strip("/") or "local-pdf"


def _local_public_url(tenant_id: UUID, kind: str, filename: str) -> str:
    settings = get_settings()
    base = (settings.public_api_base_url or "").rstrip("/")
    path = f"/api/public/reporte-local/{kind}/{tenant_id}/{filename}"
    return f"{base}{path}" if base else path


def build_foto_object_key(*, tenant_id: UUID, establishment_id: int) -> str:
    prefix = _fotos_prefix()
    name = f"{_safe_establishment_segment(establishment_id)}_{uuid.uuid4().hex[:12]}.jpg"
    return f"{prefix}/{tenant_id}/{name}"


def build_pdf_object_key(*, tenant_id: UUID, establishment_id: int, original_name: str) -> str:
    prefix = _pdfs_prefix()
    ext = ".pdf"
    safe = re.sub(r"[^\w.-]+", "_", Path(original_name or "documento.pdf").stem)[:80] or "documento"
    name = f"{_safe_establishment_segment(establishment_id)}_{safe}_{uuid.uuid4().hex[:8]}{ext}"
    return f"{prefix}/{tenant_id}/{name}"


def upload_reporte_local_foto(*, tenant_id: UUID, establishment_id: int, content: bytes) -> str:
    if obj.cloud_enabled():
        object_key = build_foto_object_key(tenant_id=tenant_id, establishment_id=establishment_id)
        obj.upload_bytes(object_key, content, content_type="image/jpeg")
        return obj.public_object_url(object_key)

    est = _safe_establishment_segment(establishment_id)
    filename = f"{est}_{uuid.uuid4().hex[:8]}.jpg"
    base = Path(__file__).resolve().parents[2] / "uploads" / "reporte_locales" / "fotos" / str(tenant_id)
    base.mkdir(parents=True, exist_ok=True)
    (base / filename).write_bytes(content)
    return _local_public_url(tenant_id, "foto", filename)


def upload_reporte_local_pdf(
    *,
    tenant_id: UUID,
    establishment_id: int,
    content: bytes,
    original_name: str,
) -> str:
    if obj.cloud_enabled():
        object_key = build_pdf_object_key(
            tenant_id=tenant_id,
            establishment_id=establishment_id,
            original_name=original_name,
        )
        obj.upload_bytes(object_key, content, content_type="application/pdf")
        return obj.public_object_url(object_key)

    est = _safe_establishment_segment(establishment_id)
    filename = f"{est}_{uuid.uuid4().hex[:8]}.pdf"
    base = Path(__file__).resolve().parents[2] / "uploads" / "reporte_locales" / "pdfs" / str(tenant_id)
    base.mkdir(parents=True, exist_ok=True)
    (base / filename).write_bytes(content)
    return _local_public_url(tenant_id, "pdf", filename)


def _tenant_in_object_key(tenant_id: UUID, key: str) -> bool:
    return str(tenant_id) in key.strip("/").split("/")


def read_local_reporte_local_file(
    tenant_id: UUID,
    kind: str,
    filename: str,
) -> tuple[bytes, str] | None:
    if kind not in ("foto", "pdf"):
        return None
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        return None
    sub = "fotos" if kind == "foto" else "pdfs"
    path = (
        Path(__file__).resolve().parents[2]
        / "uploads"
        / "reporte_locales"
        / sub
        / str(tenant_id)
        / safe
    )
    if not path.is_file():
        return None
    mime, _ = mimetypes.guess_type(safe)
    default = "image/jpeg" if kind == "foto" else "application/pdf"
    return path.read_bytes(), (mime or default).split(";")[0].strip() or default


def read_reporte_local_file_bytes(stored: str, tenant_id: UUID) -> tuple[bytes, str] | None:
    raw = (stored or "").strip()
    if not raw:
        return None

    for kind in ("foto", "pdf"):
        marker = f"/api/public/reporte-local/{kind}/{tenant_id}/"
        if marker in raw:
            filename = raw.split(marker, 1)[-1].split("?")[0]
            return read_local_reporte_local_file(tenant_id, kind, filename)

    if obj.cloud_enabled():
        key = obj.parse_object_key(raw)
        if key and _tenant_in_object_key(tenant_id, key):
            data = obj.download_stored(raw)
            if data is not None:
                mime, _ = mimetypes.guess_type(key)
                default = "image/jpeg" if key.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) else "application/pdf"
                return data, (mime or default).split(";")[0].strip() or default

        fotos_prefix = _fotos_prefix()
        pdfs_prefix = _pdfs_prefix()
        key = raw.lstrip("/")
        if key.startswith(f"{fotos_prefix}/") or key.startswith(f"{pdfs_prefix}/"):
            if _tenant_in_object_key(tenant_id, key):
                try:
                    data = obj.download_bytes(key)
                except Exception:
                    return None
                mime, _ = mimetypes.guess_type(key)
                default = "image/jpeg" if key.startswith(f"{fotos_prefix}/") else "application/pdf"
                return data, (mime or default).split(";")[0].strip() or default

    return None


def resolve_gcs_object_key(stored: str, tenant_id: UUID) -> str | None:
    """Devuelve la clave de objeto si la URL/clave pertenece al tenant."""
    raw = (stored or "").strip()
    if not raw or not obj.cloud_enabled():
        return None

    fotos_prefix = _fotos_prefix()
    pdfs_prefix = _pdfs_prefix()
    key = obj.parse_object_key(raw) or raw.lstrip("/")
    if not key or not _tenant_in_object_key(tenant_id, key):
        return None
    if key.startswith(f"{fotos_prefix}/") or key.startswith(f"{pdfs_prefix}/"):
        return key
    return None


def _is_local_stored_url(stored: str, tenant_id: UUID) -> bool:
    raw = (stored or "").strip()
    if not raw:
        return False
    for kind in ("foto", "pdf"):
        marker = f"/api/public/reporte-local/{kind}/{tenant_id}/"
        if marker in raw:
            return True
    return False


def build_reporte_local_api_download_path(stored: str) -> str:
    return f"/api/inventory/reporte-locales/download/file?src={quote(stored.strip(), safe='')}"


def generate_reporte_local_signed_url(
    stored: str,
    tenant_id: UUID,
    *,
    download_filename: str,
    expiration_minutes: int | None = None,
) -> tuple[str, datetime | None]:
    """URL firmada (R2/GCS) o ruta API autenticada en desarrollo local."""
    from app.core.export_storage import generate_signed_download_url

    settings = get_settings()
    key = resolve_gcs_object_key(stored, tenant_id)
    if key and obj.cloud_enabled():
        url, expires_at = generate_signed_download_url(
            key,
            filename=download_filename,
            expiration_minutes=expiration_minutes,
        )
        return url, expires_at

    if _is_local_stored_url(stored, tenant_id) or read_reporte_local_file_bytes(stored, tenant_id):
        base = (settings.public_api_base_url or "").strip().rstrip("/")
        path = build_reporte_local_api_download_path(stored)
        return (f"{base}{path}" if base else path), None

    raise FileNotFoundError("Archivo no encontrado")
