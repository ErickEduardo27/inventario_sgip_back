"""Logo del tenant (PDF ficha inventario): GCS en producción, disco local en desarrollo."""

from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import UUID

from app.core.config import get_settings

ALLOWED_LOGO_MIMES = frozenset({"image/png", "image/jpeg"})
MAX_LOGO_BYTES = 2 * 1024 * 1024
_GCS_HOST = "storage.googleapis.com"


def _ext_for_mime(mime: str) -> str:
    m = mime.lower().split(";")[0].strip()
    return "jpg" if m == "image/jpeg" else "png"


LogoKind = str  # "portal" | "pdf"


def _logo_stem(kind: LogoKind = "portal") -> str:
    return "logo-pdf" if kind == "pdf" else "logo"


def build_logo_object_key(*, tenant_id: UUID, ext: str, kind: LogoKind = "portal") -> str:
    settings = get_settings()
    prefix = (settings.gcs_logos_prefix or "tenant-logos").strip("/") or "tenant-logos"
    return f"{prefix}/{tenant_id}/{_logo_stem(kind)}.{ext}"


def _gcs_client():
    from google.cloud import storage

    settings = get_settings()
    creds = settings.google_application_credentials.strip()
    if creds:
        return storage.Client.from_service_account_json(creds)
    return storage.Client()


def _gcs_public_url(bucket: str, object_key: str) -> str:
    return f"https://{_GCS_HOST}/{bucket}/{object_key}"


def _local_public_url(tenant_id: UUID, filename: str) -> str:
    settings = get_settings()
    base = (settings.public_api_base_url or "").rstrip("/")
    path = f"/api/public/tenant-logo/{tenant_id}/{filename}"
    return f"{base}{path}" if base else path


def upload_tenant_logo(*, tenant_id: UUID, content: bytes, content_type: str, kind: LogoKind = "portal") -> str:
    if len(content) > MAX_LOGO_BYTES:
        raise ValueError("El logo no debe superar 2 MB")
    mime = (content_type or "").lower().split(";")[0].strip()
    if mime not in ALLOWED_LOGO_MIMES:
        raise ValueError("Formato no permitido. Use PNG o JPEG.")
    ext = _ext_for_mime(mime)
    stem = _logo_stem(kind)

    settings = get_settings()
    if settings.gcs_bucket:
        object_key = build_logo_object_key(tenant_id=tenant_id, ext=ext, kind=kind)
        client = _gcs_client()
        blob = client.bucket(settings.gcs_bucket).blob(object_key)
        blob.upload_from_string(content, content_type=mime)
        return _gcs_public_url(settings.gcs_bucket, object_key)

    base = Path(__file__).resolve().parents[2] / "uploads" / "tenant-logos" / str(tenant_id)
    base.mkdir(parents=True, exist_ok=True)
    for old in base.glob(f"{stem}.*"):
        old.unlink(missing_ok=True)
    filename = f"{stem}.{ext}"
    (base / filename).write_bytes(content)
    return _local_public_url(tenant_id, filename)


def _mime_from_bytes(content: bytes) -> str:
    if content[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if content[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    return "image/png"


def read_local_tenant_logo(tenant_id: UUID, filename: str) -> tuple[bytes, str] | None:
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        return None
    path = Path(__file__).resolve().parents[2] / "uploads" / "tenant-logos" / str(tenant_id) / safe
    if not path.is_file():
        return None
    mime, _ = mimetypes.guess_type(safe)
    return path.read_bytes(), (mime or "image/png").split(";")[0].strip() or "image/png"


def read_stored_logo_file(tenant_id: UUID, filename: str) -> tuple[bytes, str] | None:
    """Disco local o GCS (bucket privado). Para miniaturas y login."""
    pack = read_local_tenant_logo(tenant_id, filename)
    if pack:
        return pack
    settings = get_settings()
    if not settings.gcs_bucket:
        return None
    safe = Path(filename).name
    if safe != filename or ".." in filename:
        return None
    prefix = (settings.gcs_logos_prefix or "tenant-logos").strip("/") or "tenant-logos"
    key = f"{prefix}/{tenant_id}/{safe}"
    try:
        data = _gcs_client().bucket(settings.gcs_bucket).blob(key).download_as_bytes()
    except Exception:
        return None
    if not data:
        return None
    return data, _mime_from_bytes(data)


def _parse_gcs_url(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url.strip())
    if parsed.netloc != _GCS_HOST:
        return None
    path = unquote(parsed.path or "").lstrip("/")
    if not path or "/" not in path:
        return None
    bucket, key = path.split("/", 1)
    return bucket, key


def read_tenant_logo_bytes(logo_url: str | None, tenant_id: UUID) -> bytes | None:
    if not logo_url or not str(logo_url).strip():
        return None
    url = str(logo_url).strip()
    marker = f"/api/public/tenant-logo/{tenant_id}/"
    if marker in url:
        filename = url.split(marker, 1)[-1].split("?")[0]
        pack = read_local_tenant_logo(tenant_id, filename)
        return pack[0] if pack else None
    gcs = _parse_gcs_url(url)
    if gcs:
        bucket, key = gcs
        try:
            return _gcs_client().bucket(bucket).blob(key).download_as_bytes()
        except Exception:
            return None
    if url.startswith("http://") or url.startswith("https://"):
        try:
            import urllib.request

            with urllib.request.urlopen(url, timeout=15) as resp:
                return resp.read()
        except Exception:
            return None
    return None


def delete_tenant_logo_object(logo_url: str | None, tenant_id: UUID) -> None:
    if not logo_url or not str(logo_url).strip():
        return
    url = str(logo_url).strip()
    marker = f"/api/public/tenant-logo/{tenant_id}/"
    if marker in url:
        filename = url.split(marker, 1)[-1].split("?")[0]
        safe = Path(filename).name
        path = Path(__file__).resolve().parents[2] / "uploads" / "tenant-logos" / str(tenant_id) / safe
        path.unlink(missing_ok=True)
        return
    gcs = _parse_gcs_url(url)
    if not gcs:
        return
    bucket, key = gcs
    try:
        _gcs_client().bucket(bucket).blob(key).delete()
    except Exception:
        pass
