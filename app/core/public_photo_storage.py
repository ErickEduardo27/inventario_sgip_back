"""Fotos servidas por URL pública no adivinable (personas, bienes margesi).

GCS en producción, disco local en desarrollo. En ambos casos la foto se sirve por
``/api/public/{kind}-photo/{tenant_id}/{filename}``; el nombre de archivo es un UUID aleatorio.
La ruta relativa devuelta cabe en columnas cortas (≈100 caracteres).
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import UUID

from app.core.config import get_settings

PhotoKind = Literal["person", "margesi"]

MAX_PHOTO_BYTES = 5 * 1024 * 1024
_FILENAME_RE = re.compile(r"^[a-f0-9]{32}\.(jpg|png|webp)$")
_MIME_BY_EXT = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
_MAGIC: tuple[tuple[bytes, str, str], ...] = (
    (b"\xff\xd8\xff", "jpg", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png", "image/png"),
)


@dataclass(frozen=True)
class _KindConfig:
    local_dir: str
    route_segment: str

    def gcs_prefix(self, kind: PhotoKind) -> str:
        settings = get_settings()
        raw = settings.gcs_person_photos_prefix if kind == "person" else settings.gcs_margesi_photos_prefix
        default = "person-photos" if kind == "person" else "margesi-photos"
        return (raw or default).strip("/") or default


_KINDS: dict[PhotoKind, _KindConfig] = {
    "person": _KindConfig(local_dir="personas", route_segment="person-photo"),
    "margesi": _KindConfig(local_dir="margesi", route_segment="margesi-photo"),
}


def _detect_image(content: bytes) -> tuple[str, str] | None:
    for magic, ext, mime in _MAGIC:
        if content.startswith(magic):
            return ext, mime
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None


def _local_dir(kind: PhotoKind, tenant_id: UUID) -> Path:
    return Path(__file__).resolve().parents[2] / "uploads" / _KINDS[kind].local_dir / str(tenant_id)


def _object_key(kind: PhotoKind, tenant_id: UUID, filename: str) -> str:
    return f"{_KINDS[kind].gcs_prefix(kind)}/{tenant_id}/{filename}"


def _gcs_bucket():
    from google.cloud import storage

    settings = get_settings()
    creds = settings.google_application_credentials.strip()
    client = storage.Client.from_service_account_json(creds) if creds else storage.Client()
    return client.bucket(settings.gcs_bucket)


def public_path(kind: PhotoKind, tenant_id: UUID, filename: str) -> str:
    return f"/api/public/{_KINDS[kind].route_segment}/{tenant_id}/{filename}"


def upload_photo(kind: PhotoKind, *, tenant_id: UUID, content: bytes) -> str:
    """Valida y guarda la imagen; devuelve la ruta pública relativa a guardar en BD."""
    if not content:
        raise ValueError("Archivo vacío")
    if len(content) > MAX_PHOTO_BYTES:
        raise ValueError("La foto supera 5 MB")
    detected = _detect_image(content)
    if not detected:
        raise ValueError("Formato no soportado. Use JPG, PNG o WEBP")
    ext, mime = detected
    filename = f"{uuid.uuid4().hex}.{ext}"

    if get_settings().gcs_bucket:
        _gcs_bucket().blob(_object_key(kind, tenant_id, filename)).upload_from_string(content, content_type=mime)
    else:
        base = _local_dir(kind, tenant_id)
        base.mkdir(parents=True, exist_ok=True)
        (base / filename).write_bytes(content)
    return public_path(kind, tenant_id, filename)


def read_photo(kind: PhotoKind, tenant_id: UUID, filename: str) -> tuple[bytes, str] | None:
    m = _FILENAME_RE.fullmatch(filename or "")
    if not m:
        return None
    mime = _MIME_BY_EXT[m.group(1)]
    if get_settings().gcs_bucket:
        try:
            return _gcs_bucket().blob(_object_key(kind, tenant_id, filename)).download_as_bytes(), mime
        except Exception:
            return None
    path = _local_dir(kind, tenant_id) / filename
    if not path.is_file():
        return None
    return path.read_bytes(), mime


def _filename_from_stored(kind: PhotoKind, tenant_id: UUID, stored: str | None) -> str | None:
    raw = (stored or "").strip()
    marker = public_path(kind, tenant_id, "")
    if marker not in raw:
        return None
    name = raw.split(marker, 1)[-1].split("?")[0]
    return name if _FILENAME_RE.fullmatch(name) else None


def delete_photo(kind: PhotoKind, tenant_id: UUID, stored: str | None) -> None:
    """Borra la foto referenciada si la gestiona este módulo (best effort; nunca lanza).

    Valores legados (URLs externas, nombres sueltos) se ignoran.
    """
    filename = _filename_from_stored(kind, tenant_id, stored)
    if not filename:
        return
    try:
        if get_settings().gcs_bucket:
            _gcs_bucket().blob(_object_key(kind, tenant_id, filename)).delete()
        else:
            (_local_dir(kind, tenant_id) / filename).unlink(missing_ok=True)
    except Exception:
        pass
