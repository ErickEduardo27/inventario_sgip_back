"""Almacenamiento de exportaciones CSV (GCS en producción, local en dev)."""

from __future__ import annotations

import mimetypes
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings

LOCAL_PREFIX = "local:"


def _safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = re.sub(r"[^\w.\-]", "_", base)
    return cleaned or "export.csv"


def _content_type(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "text/csv"


def build_export_object_key(*, module: str, tenant_id: UUID, job_id: UUID, filename: str) -> str:
    settings = get_settings()
    prefix = (settings.gcs_export_prefix or "exports").strip("/") or "exports"
    return f"{prefix}/{module}/{tenant_id}/{job_id}/{_safe_filename(filename)}"


def upload_export_file(
    *,
    module: str,
    tenant_id: UUID,
    job_id: UUID,
    filename: str,
    content: bytes,
) -> str:
    """Sube bytes y devuelve la ruta de objeto (GCS key o ``local:/path``)."""
    settings = get_settings()
    if settings.gcs_bucket:
        from google.cloud import storage

        object_key = build_export_object_key(
            module=module,
            tenant_id=tenant_id,
            job_id=job_id,
            filename=filename,
        )
        client = _gcs_client()
        blob = client.bucket(settings.gcs_bucket).blob(object_key)
        blob.upload_from_string(content, content_type=_content_type(filename))
        return object_key

    suffix = Path(filename).suffix or ".csv"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix=f"export_{module}_")
    try:
        tmp.write(content)
        tmp.flush()
        return f"{LOCAL_PREFIX}{tmp.name}"
    finally:
        tmp.close()


def read_export_file(storage_path: str) -> bytes:
    if storage_path.startswith(LOCAL_PREFIX):
        return Path(storage_path[len(LOCAL_PREFIX) :]).read_bytes()

    settings = get_settings()
    if not settings.gcs_bucket:
        raise RuntimeError("GCS_BUCKET no configurado")
    client = _gcs_client()
    blob = client.bucket(settings.gcs_bucket).blob(storage_path)
    return blob.download_as_bytes()


def generate_signed_download_url(
    object_key: str,
    *,
    filename: str,
    expiration_minutes: int | None = None,
) -> tuple[str, datetime]:
    settings = get_settings()
    if not settings.gcs_bucket:
        raise RuntimeError("GCS_BUCKET no configurado")

    ttl = expiration_minutes if expiration_minutes is not None else settings.gcs_export_signed_url_ttl_minutes
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=max(1, ttl))
    blob = _gcs_client().bucket(settings.gcs_bucket).blob(object_key)
    url = blob.generate_signed_url(
        version="v4",
        expiration=expires_at,
        method="GET",
        response_disposition=f'attachment; filename="{_safe_filename(filename)}"',
    )
    return url, expires_at


def build_api_download_url(job_id: UUID) -> str:
    """URL del proxy API para descargas locales (sin GCS)."""
    settings = get_settings()
    base = (settings.public_api_base_url or "").strip().rstrip("/") or "http://127.0.0.1:8000"
    return f"{base}/api/inventory/descarga-archivos/{job_id}/file"


def resolve_download_url(
    *,
    storage_path: str,
    filename: str,
    job_id: UUID,
) -> tuple[str, datetime | None]:
    """Devuelve URL firmada de GCS o proxy API en desarrollo local."""
    if storage_path.startswith(LOCAL_PREFIX):
        return build_api_download_url(job_id), None

    url, expires_at = generate_signed_download_url(storage_path, filename=filename)
    return url, expires_at


def refresh_download_url_if_needed(
    *,
    storage_path: str | None,
    filename: str,
    job_id: UUID,
    current_url: str | None,
    expires_at: datetime | None,
) -> tuple[str | None, datetime | None]:
    if not storage_path:
        return current_url, expires_at

    if storage_path.startswith(LOCAL_PREFIX):
        return build_api_download_url(job_id), None

    now = datetime.now(timezone.utc)
    if current_url and expires_at and expires_at > now + timedelta(minutes=5):
        return current_url, expires_at

    url, new_expires = generate_signed_download_url(storage_path, filename=filename)
    return url, new_expires


def _gcs_client():
    from google.cloud import storage

    settings = get_settings()
    creds = settings.google_application_credentials.strip()
    if creds:
        return storage.Client.from_service_account_json(creds)
    return storage.Client()
