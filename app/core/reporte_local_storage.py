"""Archivos de Reporte Locales (fotos y PDF): GCS en producción, disco local en desarrollo."""

from __future__ import annotations

import mimetypes
import re
import uuid
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings

MAX_FOTOS = 5
MAX_PDFS = 2
LOCAL_PREFIX = "local:"
_GCS_HOST = "storage.googleapis.com"


def _safe_establishment_segment(establishment_id: int) -> str:
    return re.sub(r"[^\w.-]+", "_", str(establishment_id)) or "local"


def _fotos_prefix() -> str:
    settings = get_settings()
    return (settings.gcs_local_fotos_prefix or "local-fotos").strip("/") or "local-fotos"


def _pdfs_prefix() -> str:
    settings = get_settings()
    return (settings.gcs_local_pdf_prefix or "local-pdf").strip("/") or "local-pdf"


def _gcs_client():
    from google.cloud import storage

    settings = get_settings()
    creds = settings.google_application_credentials.strip()
    if creds:
        return storage.Client.from_service_account_json(creds)
    return storage.Client()


def _gcs_public_url(bucket: str, object_key: str) -> str:
    return f"https://{_GCS_HOST}/{bucket}/{object_key}"


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
    settings = get_settings()
    if settings.gcs_bucket:
        object_key = build_foto_object_key(tenant_id=tenant_id, establishment_id=establishment_id)
        client = _gcs_client()
        blob = client.bucket(settings.gcs_bucket).blob(object_key)
        blob.upload_from_string(content, content_type="image/jpeg")
        return _gcs_public_url(settings.gcs_bucket, object_key)

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
    settings = get_settings()
    if settings.gcs_bucket:
        object_key = build_pdf_object_key(
            tenant_id=tenant_id,
            establishment_id=establishment_id,
            original_name=original_name,
        )
        client = _gcs_client()
        blob = client.bucket(settings.gcs_bucket).blob(object_key)
        blob.upload_from_string(content, content_type="application/pdf")
        return _gcs_public_url(settings.gcs_bucket, object_key)

    est = _safe_establishment_segment(establishment_id)
    filename = f"{est}_{uuid.uuid4().hex[:8]}.pdf"
    base = Path(__file__).resolve().parents[2] / "uploads" / "reporte_locales" / "pdfs" / str(tenant_id)
    base.mkdir(parents=True, exist_ok=True)
    (base / filename).write_bytes(content)
    return _local_public_url(tenant_id, "pdf", filename)


def _parse_gcs_url(url: str) -> tuple[str, str] | None:
    from urllib.parse import unquote, urlparse

    parsed = urlparse(url.strip())
    if parsed.netloc != _GCS_HOST:
        return None
    path = unquote(parsed.path or "").lstrip("/")
    if not path or "/" not in path:
        return None
    bucket, key = path.split("/", 1)
    return bucket, key


def _tenant_in_object_key(tenant_id: UUID, key: str) -> bool:
    return str(tenant_id) in key.strip("/").split("/")


def _download_gcs_object(bucket: str, key: str) -> tuple[bytes, str] | None:
    try:
        data = _gcs_client().bucket(bucket).blob(key).download_as_bytes()
    except Exception:
        return None
    mime, _ = mimetypes.guess_type(key)
    return data, (mime or "application/octet-stream").split(";")[0].strip() or "application/octet-stream"


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

    gcs = _parse_gcs_url(raw)
    if gcs:
        bucket, key = gcs
        if not _tenant_in_object_key(tenant_id, key):
            return None
        return _download_gcs_object(bucket, key)

    settings = get_settings()
    fotos_prefix = _fotos_prefix()
    pdfs_prefix = _pdfs_prefix()
    if settings.gcs_bucket:
        key = raw.lstrip("/")
        if key.startswith(f"{fotos_prefix}/") or key.startswith(f"{pdfs_prefix}/"):
            if _tenant_in_object_key(tenant_id, key):
                return _download_gcs_object(settings.gcs_bucket, key)

    return None
