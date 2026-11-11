"""Almacenamiento de objetos: Cloudflare R2 (S3), GCS o disco local.

Si hay credenciales R2, R2 tiene prioridad (los archivos ya migrados se leen por la misma clave).
Las URLs antiguas ``https://storage.googleapis.com/{bucket}/{key}`` se resuelven extrayendo ``key``.
"""

from __future__ import annotations

import logging
import mimetypes
import threading
from datetime import datetime, timedelta, timezone
from typing import BinaryIO, Literal
from urllib.parse import unquote, urlparse

from app.core.config import get_settings

logger = logging.getLogger(__name__)

StorageBackend = Literal["r2", "gcs", "local"]

_GCS_HOST = "storage.googleapis.com"
_client_local = threading.local()


def storage_backend() -> StorageBackend:
    settings = get_settings()
    forced = (settings.storage_backend or "auto").strip().lower()
    if forced in ("r2", "gcs", "local"):
        if forced == "r2" and not _r2_ready(settings):
            raise RuntimeError("STORAGE_BACKEND=r2 pero faltan R2_BUCKET / R2_ACCOUNT_ID / claves")
        if forced == "gcs" and not settings.gcs_bucket.strip():
            raise RuntimeError("STORAGE_BACKEND=gcs pero GCS_BUCKET está vacío")
        return forced  # type: ignore[return-value]
    if _r2_ready(settings):
        return "r2"
    if settings.gcs_bucket.strip():
        return "gcs"
    return "local"


def cloud_enabled() -> bool:
    return storage_backend() in ("r2", "gcs")


def active_bucket() -> str:
    settings = get_settings()
    backend = storage_backend()
    if backend == "r2":
        return settings.r2_bucket.strip()
    if backend == "gcs":
        return settings.gcs_bucket.strip()
    return ""


def _r2_ready(settings) -> bool:
    return bool(
        settings.r2_bucket.strip()
        and settings.r2_account_id.strip()
        and settings.r2_access_key_id.strip()
        and settings.r2_secret_access_key.strip()
    )


def _r2_endpoint(settings) -> str:
    custom = (settings.r2_endpoint_url or "").strip().rstrip("/")
    if custom:
        return custom
    return f"https://{settings.r2_account_id.strip()}.r2.cloudflarestorage.com"


def _s3_client():
    client = getattr(_client_local, "s3", None)
    if client is not None:
        return client
    import boto3
    from botocore.config import Config

    settings = get_settings()
    client = boto3.client(
        "s3",
        endpoint_url=_r2_endpoint(settings),
        aws_access_key_id=settings.r2_access_key_id.strip(),
        aws_secret_access_key=settings.r2_secret_access_key.strip(),
        region_name=(settings.r2_region or "auto").strip() or "auto",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    _client_local.s3 = client
    return client


def _gcs_client():
    client = getattr(_client_local, "gcs", None)
    if client is not None:
        return client
    from google.cloud import storage

    settings = get_settings()
    creds = settings.google_application_credentials.strip()
    client = storage.Client.from_service_account_json(creds) if creds else storage.Client()
    _client_local.gcs = client
    return client


def public_object_url(object_key: str) -> str:
    """URL a guardar en BD para objetos «públicos» (fotos). Con R2 privado preferir clave + preview auth."""
    key = object_key.lstrip("/")
    settings = get_settings()
    backend = storage_backend()
    if backend == "r2":
        base = (settings.r2_public_base_url or "").strip().rstrip("/")
        if base:
            return f"{base}/{key}"
        # Sin dominio público: guardar clave; el front usa preview autenticado.
        return key
    if backend == "gcs":
        return f"https://{_GCS_HOST}/{settings.gcs_bucket.strip()}/{key}"
    return key


def parse_object_key(stored: str, *, expected_bucket: str | None = None) -> str | None:
    """Extrae la clave de objeto desde URL GCS, URL R2/CDN o clave cruda."""
    raw = (stored or "").strip()
    if not raw:
        return None

    if "://" not in raw and not raw.startswith("/"):
        return raw.lstrip("/")

    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    path = unquote(parsed.path or "").lstrip("/")
    if not path:
        return None

    settings = get_settings()
    bucket = (expected_bucket or active_bucket() or settings.gcs_bucket or settings.r2_bucket).strip()

    if host == _GCS_HOST or host.endswith(".storage.googleapis.com"):
        if "/" not in path:
            return None
        bkt, key = path.split("/", 1)
        if bucket and bkt != bucket:
            # Objeto migrado: misma clave en R2 aunque el bucket de la URL sea el de GCS.
            return key
        return key

    if "r2.cloudflarestorage.com" in host or host.endswith(".r2.dev"):
        # path-style: /bucket/key  o virtual-host: /key
        if bucket and path.startswith(f"{bucket}/"):
            return path[len(bucket) + 1 :]
        return path

    public_base = (settings.r2_public_base_url or "").strip().rstrip("/")
    if public_base:
        public_host = urlparse(public_base).netloc.lower()
        if host == public_host:
            public_path = urlparse(public_base).path.rstrip("/").lstrip("/")
            if public_path and path.startswith(f"{public_path}/"):
                return path[len(public_path) + 1 :]
            return path

    return None


def upload_bytes(object_key: str, content: bytes, *, content_type: str | None = None) -> str:
    """Sube bytes y devuelve la clave de objeto."""
    key = object_key.lstrip("/")
    mime = content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
    backend = storage_backend()
    if backend == "r2":
        _s3_client().put_object(Bucket=active_bucket(), Key=key, Body=content, ContentType=mime)
        return key
    if backend == "gcs":
        _gcs_client().bucket(active_bucket()).blob(key).upload_from_string(content, content_type=mime)
        return key
    raise RuntimeError("Almacenamiento en la nube no configurado")


def upload_file(object_key: str, file_path: str, *, content_type: str | None = None) -> str:
    key = object_key.lstrip("/")
    mime = content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
    backend = storage_backend()
    if backend == "r2":
        _s3_client().upload_file(file_path, active_bucket(), key, ExtraArgs={"ContentType": mime})
        return key
    if backend == "gcs":
        _gcs_client().bucket(active_bucket()).blob(key).upload_from_filename(file_path, content_type=mime)
        return key
    raise RuntimeError("Almacenamiento en la nube no configurado")


def download_bytes(object_key: str) -> bytes:
    key = object_key.lstrip("/")
    backend = storage_backend()
    if backend == "r2":
        return _s3_client().get_object(Bucket=active_bucket(), Key=key)["Body"].read()
    if backend == "gcs":
        return _gcs_client().bucket(active_bucket()).blob(key).download_as_bytes()
    raise RuntimeError("Almacenamiento en la nube no configurado")


def download_stored(stored: str) -> bytes | None:
    """Descarga desde una URL/clave guardada en BD (compatible con URLs GCS antiguas)."""
    key = parse_object_key(stored)
    if not key:
        return None
    try:
        return download_bytes(key)
    except Exception:
        logger.warning("No se pudo leer objeto %s", key, exc_info=True)
        return None


def object_exists(object_key: str) -> bool:
    key = (object_key or "").lstrip("/")
    if not key:
        return False
    backend = storage_backend()
    try:
        if backend == "r2":
            _s3_client().head_object(Bucket=active_bucket(), Key=key)
            return True
        if backend == "gcs":
            return bool(_gcs_client().bucket(active_bucket()).blob(key).exists())
    except Exception:
        return False
    return False


def delete_object(object_key: str) -> None:
    key = (object_key or "").lstrip("/")
    if not key:
        return
    backend = storage_backend()
    try:
        if backend == "r2":
            _s3_client().delete_object(Bucket=active_bucket(), Key=key)
        elif backend == "gcs":
            from google.api_core.exceptions import NotFound

            try:
                _gcs_client().bucket(active_bucket()).blob(key).delete()
            except NotFound:
                pass
    except Exception:
        logger.warning("No se pudo borrar objeto %s", key, exc_info=True)


def open_write_stream(object_key: str, *, content_type: str | None = None) -> tuple[BinaryIO, str]:
    """Abre un writer; en R2 escribe a temp y sube al cerrar ``finalize_write_stream``."""
    import tempfile
    from pathlib import Path

    key = object_key.lstrip("/")
    mime = content_type or mimetypes.guess_type(key)[0] or "application/octet-stream"
    backend = storage_backend()
    if backend == "gcs":
        blob = _gcs_client().bucket(active_bucket()).blob(key)
        raw = blob.open("wb", chunk_size=16 * 1024 * 1024, content_type=mime, ignore_flush=True)
        return raw, key
    if backend == "r2":
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=Path(key).suffix or ".bin")
        tmp._sgip_r2_key = key  # type: ignore[attr-defined]
        tmp._sgip_r2_mime = mime  # type: ignore[attr-defined]
        tmp._sgip_r2_path = tmp.name  # type: ignore[attr-defined]
        return tmp, key
    raise RuntimeError("Almacenamiento en la nube no configurado")


def finalize_write_stream(fh: BinaryIO) -> None:
    """Cierra el writer de ``open_write_stream`` y confirma la subida."""
    import os
    from pathlib import Path

    path = getattr(fh, "_sgip_r2_path", None)
    key = getattr(fh, "_sgip_r2_key", None)
    mime = getattr(fh, "_sgip_r2_mime", None)
    if path and key:
        try:
            fh.flush()
            fh.close()
            upload_file(key, path, content_type=mime)
        finally:
            Path(path).unlink(missing_ok=True)
        return
    fh.close()


def abort_write_stream(fh: BinaryIO) -> None:
    from pathlib import Path

    path = getattr(fh, "_sgip_r2_path", None)
    try:
        fh.close()
    except Exception:
        pass
    if path:
        Path(path).unlink(missing_ok=True)


def generate_signed_download_url(
    object_key: str,
    *,
    filename: str,
    expiration_minutes: int | None = None,
) -> tuple[str, datetime]:
    settings = get_settings()
    key = object_key.lstrip("/")
    ttl = expiration_minutes if expiration_minutes is not None else settings.gcs_export_signed_url_ttl_minutes
    ttl = max(1, int(ttl))
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl)
    safe_name = filename.replace('"', "")
    disposition = f'attachment; filename="{safe_name}"'
    backend = storage_backend()

    if backend == "r2":
        url = _s3_client().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": active_bucket(),
                "Key": key,
                "ResponseContentDisposition": disposition,
            },
            ExpiresIn=ttl * 60,
        )
        return url, expires_at

    if backend == "gcs":
        blob = _gcs_client().bucket(active_bucket()).blob(key)
        url = blob.generate_signed_url(
            version="v4",
            expiration=expires_at,
            method="GET",
            response_disposition=disposition,
        )
        return url, expires_at

    raise RuntimeError("Almacenamiento en la nube no configurado")
