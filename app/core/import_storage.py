"""Almacenamiento de archivos de importación masiva (GCS en producción, local en dev)."""

from __future__ import annotations

import mimetypes
import re
import tempfile
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings

LOCAL_PREFIX = "local:"


def _safe_filename(name: str) -> str:
    base = Path(name).name
    cleaned = re.sub(r"[^\w.\-]", "_", base)
    return cleaned or "upload.xlsx"


def _content_type(filename: str) -> str:
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def build_import_object_key(*, module: str, tenant_id: UUID, job_id: UUID, filename: str) -> str:
    settings = get_settings()
    prefix = settings.gcs_import_prefix.strip("/") or "imports"
    return f"{prefix}/{module}/{tenant_id}/{job_id}/{_safe_filename(filename)}"


def upload_import_file(
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

        object_key = build_import_object_key(
            module=module,
            tenant_id=tenant_id,
            job_id=job_id,
            filename=filename,
        )
        client = _gcs_client()
        blob = client.bucket(settings.gcs_bucket).blob(object_key)
        blob.upload_from_string(content, content_type=_content_type(filename))
        return object_key

    suffix = Path(filename).suffix or ".xlsx"
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, prefix=f"import_{module}_")
    try:
        tmp.write(content)
        tmp.flush()
        return f"{LOCAL_PREFIX}{tmp.name}"
    finally:
        tmp.close()


def download_import_file(storage_path: str) -> bytes:
    if storage_path.startswith(LOCAL_PREFIX):
        return Path(storage_path[len(LOCAL_PREFIX) :]).read_bytes()

    settings = get_settings()
    if not settings.gcs_bucket:
        raise RuntimeError("GCS_BUCKET no configurado")
    client = _gcs_client()
    blob = client.bucket(settings.gcs_bucket).blob(storage_path)
    return blob.download_as_bytes()


def delete_import_file(storage_path: str) -> None:
    if storage_path.startswith(LOCAL_PREFIX):
        path = Path(storage_path[len(LOCAL_PREFIX) :])
        if path.exists():
            path.unlink(missing_ok=True)
        return

    settings = get_settings()
    if not settings.gcs_bucket:
        return
    client = _gcs_client()
    blob = client.bucket(settings.gcs_bucket).blob(storage_path)
    if blob.exists():
        blob.delete()


def _gcs_client():
    from google.cloud import storage

    settings = get_settings()
    creds = settings.google_application_credentials.strip()
    if creds:
        return storage.Client.from_service_account_json(creds)
    return storage.Client()
