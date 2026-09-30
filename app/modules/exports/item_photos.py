"""ZIP de fotos de bienes por local.

Volumen real: hasta ~31 mil bienes y ~78 mil fotos en un solo local (≈ 20 GB). Por eso:

- **Partes**: el local se divide en ZIP de hasta ``PART_MAX_PHOTOS`` fotos (≈ 3–4 GB). Las 3 fotos de un bien
  siempre quedan en la misma parte. La mayoría de locales cabe en un solo ZIP.
- **Descarga en paralelo** desde GCS (un cliente por hilo) manteniendo el orden por N° de inventario.
- **ZIP en streaming directo a GCS** (sin disco intermedio; memoria acotada) y sin recomprimir (las JPEG ya
  vienen comprimidas: ``ZIP_STORED`` es mucho más rápido y el tamaño es el mismo).

Nombres dentro del ZIP: ``{inv_num}-I`` (foto 1), ``{inv_num}-P`` (foto 2), ``{inv_num}-S`` (foto 3).
"""

from __future__ import annotations

import re
import zipfile
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

if TYPE_CHECKING:
    from app.modules.exports.runner import ExportContext

MODULE = "item_photos_zip"
PART_MAX_PHOTOS = 15_000
DOWNLOAD_THREADS = 16
#: Fotos descargadas por adelantado (memoria acotada: ~64 × 300 KB).
PREFETCH = 64
SLOT_SUFFIX = {1: "I", 2: "P", 3: "S"}

_PHOTO_COLUMNS = """
    NULLIF(TRIM(COALESCE(ic.extra->>'mar_foto', ic.extra->>'foto_bien', '')), '') AS foto1,
    NULLIF(TRIM(COALESCE(ic.extra->>'mar_foto2', ic.extra->>'foto2_bien', '')), '') AS foto2,
    NULLIF(TRIM(COALESCE(ic.extra->>'mar_foto3', ic.extra->>'foto3_bien', '')), '') AS foto3
"""

# Bienes del local (vía hoja → ambiente → local) con al menos una foto.
_ITEMS_SQL = f"""
SELECT ic.id, ic.inv_num, {_PHOTO_COLUMNS}
FROM itemcards ic
JOIN cards c ON c.id = ic.id_card AND c.tenant_id = ic.tenant_id
JOIN enviroments env ON env.id = c.id_ambiente AND env.tenant_id = c.tenant_id
WHERE ic.tenant_id = CAST(:tenant_id AS uuid)
  AND env.establishment_id = :establishment_id
  AND COALESCE(ic.extra->>'mar_foto', ic.extra->>'foto_bien', ic.extra->>'mar_foto2', ic.extra->>'foto2_bien',
               ic.extra->>'mar_foto3', ic.extra->>'foto3_bien', '') <> ''
"""


@dataclass(frozen=True)
class Photo:
    inv_num: str
    slot: int
    url: str

    @property
    def entry_name(self) -> str:
        return f"{self.inv_num}-{SLOT_SUFFIX[self.slot]}{_extension(self.url)}"


def _extension(url: str) -> str:
    suffix = PurePosixPath(urlparse(url).path).suffix.lower()
    return suffix if suffix in (".jpg", ".jpeg", ".png", ".webp", ".gif") else ".jpg"


def _safe(text_value: str) -> str:
    return re.sub(r"[^\w\- ]+", "", text_value).strip().replace(" ", "_")[:60] or "local"


def _establishment(db: Session, tenant_id: UUID, establishment_id: int):
    from app.modules.inventory import models as m

    est = db.get(m.InvEstablishment, establishment_id)
    if est is None or est.tenant_id != tenant_id:
        raise ValueError("Local no encontrado")
    return est


def _photo_count(row) -> int:
    return sum(1 for u in (row.foto1, row.foto2, row.foto3) if u)


def build_plan(db: Session, tenant_id: UUID, establishment_id: int, part_max_photos: int = PART_MAX_PHOTOS) -> dict[str, Any]:
    """Cuántas fotos tiene el local y cómo se reparten en partes (rangos de id de bien, estables)."""
    est = _establishment(db, tenant_id, establishment_id)
    rows = db.execute(
        text(_ITEMS_SQL + " ORDER BY ic.id"),
        {"tenant_id": str(tenant_id), "establishment_id": establishment_id},
    ).all()
    parts: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        n = _photo_count(row)
        if current is None or current["photos"] + n > part_max_photos:
            current = {"id_from": int(row.id), "id_to": int(row.id), "items": 0, "photos": 0}
            parts.append(current)
        current["id_to"] = int(row.id)
        current["items"] += 1
        current["photos"] += n
    for i, part in enumerate(parts, start=1):
        part["part"] = i
    return {
        "establishment_id": establishment_id,
        "establishment_code": str(est.code or "").strip(),
        "establishment_description": str(est.description or "").strip(),
        "items": len(rows),
        "photos": sum(p["photos"] for p in parts),
        "part_max_photos": part_max_photos,
        "parts": parts,
    }


# --- Integración con el catálogo de exportaciones -------------------------------------


def parse_filters(filters: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """El cliente solo indica local y número de parte: los rangos salen del plan congelado (``resolve``)."""
    try:
        est_id = int(filters.get("establishment_id"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Seleccione un local") from exc
    try:
        part = int(filters.get("part") or 1)
    except (TypeError, ValueError) as exc:
        raise ValueError("Parte inválida") from exc
    run = {"establishment_id": est_id, "part": part}
    return run, dict(run)


# --- Plan congelado (manifiesto en el almacenamiento) ----------------------------------
#
# La primera vez que se genera un ZIP del local se guarda el reparto en partes. Desde entonces las partes
# (y por tanto sus ZIP guardados) no cambian aunque se agreguen o editen bienes: cualquiera descarga lo
# guardado y nada se regenera. Solo ``reset_local`` (administrador) crea un plan y ZIP nuevos.


def _manifest_name(tenant_id: UUID, establishment_id: int) -> str:
    return f"{MODULE}/{tenant_id}/manifests/{int(establishment_id)}.json"


def load_manifest(tenant_id: UUID, establishment_id: int) -> dict[str, Any] | None:
    from app.core.export_storage import read_export_json

    return read_export_json(_manifest_name(tenant_id, establishment_id))


def _lock_local(db: Session, tenant_id: UUID, establishment_id: int) -> None:
    import hashlib

    seed = int(hashlib.sha256(f"{tenant_id}:{MODULE}:plan:{establishment_id}".encode()).hexdigest()[:15], 16)
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": seed % (2**31 - 1)})


def _freeze_plan(db: Session, tenant_id: UUID, establishment_id: int) -> dict[str, Any]:
    import uuid as _uuid

    from app.core.export_storage import write_export_json

    plan = build_plan(db, tenant_id, establishment_id)
    plan["version"] = _uuid.uuid4().hex[:12]
    plan["frozen_at"] = datetime.now().astimezone().isoformat()
    write_export_json(_manifest_name(tenant_id, establishment_id), plan)
    return plan


def get_plan(db: Session, tenant_id: UUID, establishment_id: int) -> dict[str, Any]:
    """Plan congelado si el local ya se generó alguna vez; si no, el reparto que se congelará al generar."""
    _establishment(db, tenant_id, establishment_id)
    manifest = load_manifest(tenant_id, establishment_id)
    if manifest:
        return {**manifest, "frozen": True}
    return {**build_plan(db, tenant_id, establishment_id), "frozen": False, "version": None, "frozen_at": None}


def resolve(
    db: Session, tenant_id: UUID, run: dict[str, Any], _key: dict[str, Any], create: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    from app.modules.exports.specs import NotPlannedError

    est_id = int(run["establishment_id"])
    manifest = load_manifest(tenant_id, est_id)
    if manifest is None:
        if not create:
            raise NotPlannedError("El local aún no tiene ZIP generados")
        # Dos usuarios pidiendo a la vez el primer ZIP del local: uno congela el plan, el otro lo reutiliza.
        _lock_local(db, tenant_id, est_id)
        manifest = load_manifest(tenant_id, est_id) or _freeze_plan(db, tenant_id, est_id)
    parts = manifest.get("parts") or []
    part = next((p for p in parts if int(p["part"]) == int(run["part"])), None)
    if part is None:
        raise ValueError("Esa parte ya no existe en el plan del local; vuelva a abrir la descarga")
    full_run = {
        "establishment_id": est_id,
        "part": int(part["part"]),
        "parts": len(parts),
        "id_from": int(part["id_from"]),
        "id_to": int(part["id_to"]),
    }
    key = {"establishment_id": est_id, "part": full_run["part"], "parts": full_run["parts"], "version": manifest["version"]}
    return full_run, key


class LocalBusyError(Exception):
    """Hay partes del local generándose: no se puede regenerar hasta que terminen."""


def reset_local(db: Session, tenant_id: UUID, establishment_id: int) -> dict[str, Any]:
    """Regenera el plan del local (solo administradores): borra los ZIP guardados y congela un plan nuevo.

    Los ZIP viejos se eliminan del almacenamiento para no pagar dos veces el espacio.
    """
    from app.core.export_storage import delete_export_json, delete_export_object
    from app.modules.exports import service
    from app.modules.exports.specs import TENANT_SCOPE
    from app.modules.inventory.models import InvDescargaArchivo

    _establishment(db, tenant_id, establishment_id)
    _lock_local(db, tenant_id, establishment_id)
    manifest = load_manifest(tenant_id, establishment_id)
    if manifest:
        parts = manifest.get("parts") or []
        keys = [
            service.build_request_key(
                MODULE,
                tenant_id,
                {"establishment_id": establishment_id, "part": int(p["part"]), "parts": len(parts), "version": manifest["version"]},
                "zip",
                TENANT_SCOPE,
            )
            for p in parts
        ]
        rows = db.query(InvDescargaArchivo).filter(
            InvDescargaArchivo.tenant_id == tenant_id,
            InvDescargaArchivo.module == MODULE,
            InvDescargaArchivo.request_key.in_(keys),
        ).all()
        busy = [r for r in rows if r.state in service.ACTIVE_STATES and not service.is_stale(r)]
        if busy:
            raise LocalBusyError("Hay partes de este local generándose; espere a que terminen para regenerar.")
        for row in rows:
            if row.state == "success":
                delete_export_object(row.gcs_path)
                row.state = "failure"
                row.message = "Reemplazado por una versión nueva del ZIP del local"
                row.errors = [row.message]
                row.gcs_path = None
                db.add(row)
        delete_export_json(_manifest_name(tenant_id, establishment_id))
    plan = _freeze_plan(db, tenant_id, establishment_id)
    db.commit()
    return {**plan, "frozen": True}


def precheck(db: Session, tenant_id: UUID, params: dict[str, Any]) -> None:
    _establishment(db, tenant_id, int(params["establishment_id"]))


def describe(db: Session, tenant_id: UUID, params: dict[str, Any]) -> str:
    est = _establishment(db, tenant_id, int(params["establishment_id"]))
    label = f"Fotos · {str(est.code or '').strip() or est.id}"
    if int(params.get("parts") or 1) > 1:
        label += f" (parte {params['part']} de {params['parts']})"
    return label


def _load_photos(tenant_id: UUID, params: dict[str, Any]) -> tuple[list[Photo], str, str]:
    from app.db.session import SessionLocal

    sql = _ITEMS_SQL
    bind: dict[str, Any] = {"tenant_id": str(tenant_id), "establishment_id": int(params["establishment_id"])}
    if "id_from" in params:
        sql += " AND ic.id BETWEEN :id_from AND :id_to"
        bind.update(id_from=int(params["id_from"]), id_to=int(params["id_to"]))
    sql += " ORDER BY ic.inv_num, ic.id"
    with SessionLocal() as db:
        est = _establishment(db, tenant_id, int(params["establishment_id"]))
        rows = db.execute(text(sql), bind).all()
        code = str(est.code or est.id).strip()
        description = str(est.description or "").strip()
    photos: list[Photo] = []
    for row in rows:
        inv = str(row.inv_num) if row.inv_num is not None else f"sin_numero_{row.id}"
        for slot, url in ((1, row.foto1), (2, row.foto2), (3, row.foto3)):
            if url:
                photos.append(Photo(inv, slot, url))
    return photos, code, description


def generate(ctx: "ExportContext", tenant_id: UUID, params: dict[str, Any], _export_format: str):
    from app.core.export_storage import open_export_writer
    from app.core.item_photo_storage import read_item_photo_bytes
    from app.modules.exports.specs import StoredOutput

    ctx.progress(2, "Buscando fotos del local…", force=True)
    photos, code, description = _load_photos(tenant_id, params)
    if not photos:
        raise ValueError("El local no tiene fotos de bienes para descargar")

    parts = int(params.get("parts") or 1)
    part_suffix = f"_parte{params['part']}de{parts}" if parts > 1 else ""
    filename = f"fotos_{_safe(code)}{part_suffix}_{date.today().isoformat()}.zip"
    folder = _safe(f"{code} {description}") if description else _safe(code)
    total = len(photos)
    missing: list[str] = []
    stamp = datetime.now().timetuple()[:6]

    def fetch(photo: Photo) -> bytes | None:
        try:
            got = read_item_photo_bytes(photo.url, tenant_id)
        except Exception:  # noqa: BLE001 - una foto rota no debe tumbar el ZIP completo
            return None
        return got[0] if got else None

    with open_export_writer(module=MODULE, tenant_id=tenant_id, job_id=ctx.job_id, filename=filename) as target:
        with zipfile.ZipFile(target.fh, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            with ThreadPoolExecutor(max_workers=DOWNLOAD_THREADS, thread_name_prefix="foto") as pool:
                pending: deque = deque()
                queue = iter(photos)
                done = 0

                def refill() -> None:
                    while len(pending) < PREFETCH:
                        photo = next(queue, None)
                        if photo is None:
                            return
                        pending.append((photo, pool.submit(fetch, photo)))

                refill()
                # Se escribe en orden de N° de inventario aunque las descargas terminen desordenadas.
                while pending:
                    photo, future = pending.popleft()
                    data = future.result()
                    refill()
                    if data is None:
                        missing.append(f"{photo.entry_name}\t{photo.url}")
                    else:
                        info = zipfile.ZipInfo(f"{folder}/{photo.entry_name}", date_time=stamp)
                        info.compress_type = zipfile.ZIP_STORED
                        zf.writestr(info, data)
                    done += 1
                    ctx.progress(
                        3 + int(94 * done / total),
                        f"Empaquetando {_fmt(done)} de {_fmt(total)} fotos…",
                        rows_done=done,
                        rows_total=total,
                    )
            if missing:
                report = (
                    "Fotos registradas en el sistema que no se pudieron leer del almacenamiento.\n"
                    "archivo\turl\n" + "\n".join(missing) + "\n"
                )
                zf.writestr(zipfile.ZipInfo(f"{folder}/_fotos_no_disponibles.txt", date_time=stamp), report.encode("utf-8"))
        if len(missing) == total:
            raise ValueError("No se pudo leer ninguna foto del almacenamiento")
        ctx.progress(98, "Finalizando el archivo…", force=True)

    return StoredOutput(storage_path=target.storage_path, filename=filename, size=target.size)


def _fmt(n: int) -> str:
    return f"{n:,}".replace(",", ".")
