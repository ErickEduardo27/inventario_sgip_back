"""Almacenamiento de archivos de importación masiva (R2/GCS en producción, local en dev)."""

from __future__ import annotations

import mimetypes
import re
import tempfile
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings
from app.core import object_storage as obj

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
    """Sube bytes y devuelve la ruta de objeto (clave R2/GCS o ``local:/path``)."""
    if obj.cloud_enabled():
        object_key = build_import_object_key(
            module=module,
            tenant_id=tenant_id,
            job_id=job_id,
            filename=filename,
        )
        obj.upload_bytes(object_key, content, content_type=_content_type(filename))
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

    if not obj.cloud_enabled():
        raise RuntimeError("Almacenamiento en la nube no configurado (R2_BUCKET o GCS_BUCKET)")
    return obj.download_bytes(storage_path)


def delete_import_file(storage_path: str) -> None:
    if storage_path.startswith(LOCAL_PREFIX):
        path = Path(storage_path[len(LOCAL_PREFIX) :])
        if path.exists():
            path.unlink(missing_ok=True)
        return

    if not obj.cloud_enabled():
        return
    obj.delete_object(storage_path)
