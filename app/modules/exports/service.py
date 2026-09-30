"""Ciclo de vida de las exportaciones: un trabajo por clave, varios interesados.

Flujo al pedir una exportación (``request_export``), dentro de un candado transaccional por clave:

1. Se descartan trabajos "zombi" (en cola demasiado tiempo o sin latido del worker).
2. Si ya hay un trabajo activo con la misma clave → el usuario se suma como suscriptor (``joined``).
3. Si hay un archivo reciente con la misma clave y no se pidió uno nuevo → se ofrece (``available``).
4. Si el usuario ya tiene su propio trabajo activo con otra clave → límite (``ExportLimitError``).
5. Si no → se crea el trabajo y se encola en el worker (``queued``).

La base de datos solo registra transiciones; el progreso y los avisos viven en Redis (``live``).
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.exports import live
from app.modules.exports.specs import ExportSpec, get_spec, normalize_format
from app.modules.inventory.models import InvDescargaArchivo

logger = logging.getLogger(__name__)

ACTIVE_STATES = ("pending", "processing")
STALE_MESSAGE = "La exportación se interrumpió (el proceso dejó de responder). Puede generarla de nuevo."


class ExportLimitError(Exception):
    def __init__(self, message: str, job: dict[str, Any]):
        super().__init__(message)
        self.job = job


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


# --- Clave ------------------------------------------------------------------


def build_request_key(module: str, tenant_id: UUID, key_params: dict[str, Any], fmt: str, scope: str) -> str:
    """Clave estable a partir de lo que define el archivo: módulo, formato, alcance y filtros normalizados."""
    data = {"tenant_id": str(tenant_id), "module": module, "export_format": fmt, "scope": scope, **key_params}
    raw = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:40]


def _advisory_lock(db: Session, tenant_id: UUID, module: str, request_key: str) -> None:
    seed = int(hashlib.sha256(f"{tenant_id}:{module}:{request_key}".encode()).hexdigest()[:15], 16)
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": seed % (2**31 - 1)})


# --- Representación pública ----------------------------------------------------


def job_payload(row: InvDescargaArchivo, *, user_id: UUID | None = None, overlay: dict[str, str] | None = None) -> dict[str, Any]:
    """Estado público del trabajo. ``overlay`` = estado en vivo de Redis (más reciente que la base)."""
    live_state = overlay or {}
    state = live_state.get("state") or row.state
    # Redis puede ir por delante durante el proceso; un estado final de la base siempre manda.
    if row.state in ("success", "failure"):
        state = row.state
    progress = int(live_state.get("progress") or row.progress or 0) if state != "success" else 100
    fmt = live_state.get("format") or _format_from_filename(row.filename)
    try:
        spec_label = get_spec(row.module).label
    except LookupError:
        spec_label = row.module
    finished = row.updated_at if row.state in ("success", "failure") else None
    return {
        "job_id": str(row.id),
        "module": row.module,
        "label": live_state.get("label") or spec_label,
        "format": fmt,
        "state": state,
        "progress": progress,
        "message": (live_state.get("message") if row.state not in ("success", "failure") else None) or row.message or "",
        "filename": row.filename,
        "file_size_bytes": int(row.file_size_bytes) if row.file_size_bytes else None,
        "rows_done": _int_or_none(live_state.get("rows_done")),
        "rows_total": _int_or_none(live_state.get("rows_total")),
        "created_at": _iso(row.created_at),
        "finished_at": _iso(finished),
        "started_by_me": bool(user_id and row.created_by_id == user_id),
        "started_by_name": live_state.get("started_by_name") or None,
        "errors": list(row.errors or []) if row.state == "failure" else [],
    }


def _format_from_filename(filename: str | None) -> str:
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return ext if ext in ("csv", "xlsx", "zip") else "csv"


def _int_or_none(v: str | None) -> int | None:
    try:
        return int(v) if v not in (None, "") else None
    except ValueError:
        return None


def _user_name(db: Session, user_id: UUID | None) -> str:
    if not user_id:
        return ""
    from app.modules.iam.models import User

    user = db.get(User, user_id)
    return (user.full_name or user.email or "").strip() if user else ""


# --- Trabajos zombi -------------------------------------------------------------


def is_stale(row: InvDescargaArchivo, now: datetime | None = None) -> bool:
    """Trabajo activo que ya no avanza: nadie lo tomó a tiempo o el worker dejó de dar señales."""
    if row.state not in ACTIVE_STATES:
        return False
    settings = get_settings()
    now = now or _now()
    alive = live.is_alive(row.id)
    if alive:
        return False
    if row.state == "pending":
        return now - row.created_at > timedelta(minutes=settings.export_pending_timeout_minutes)
    # En proceso: el worker toca ``updated_at`` cada minuto aunque Redis no esté disponible.
    last = row.updated_at or row.created_at
    return now - last > timedelta(minutes=settings.export_stale_minutes)


def expire_stale(db: Session, row: InvDescargaArchivo) -> None:
    row.state = "failure"
    row.progress = 0
    row.message = STALE_MESSAGE
    row.errors = [STALE_MESSAGE]
    db.add(row)
    db.flush()
    live.write_job(row.id, {"state": "failure", "message": STALE_MESSAGE})
    live.publish(row.tenant_id, row.id, job_payload(row))


def _active_for_key(db: Session, tenant_id: UUID, module: str, request_key: str) -> InvDescargaArchivo | None:
    rows = db.scalars(
        select(InvDescargaArchivo)
        .where(
            InvDescargaArchivo.tenant_id == tenant_id,
            InvDescargaArchivo.module == module,
            InvDescargaArchivo.request_key == request_key,
            InvDescargaArchivo.state.in_(ACTIVE_STATES),
        )
        .order_by(InvDescargaArchivo.created_at.desc())
    ).all()
    active = None
    for row in rows:
        if is_stale(row):
            expire_stale(db, row)
        elif active is None:
            active = row
    return active


def _recent_success(db: Session, tenant_id: UUID, module: str, request_key: str) -> InvDescargaArchivo | None:
    minutes = get_settings().export_reuse_minutes
    if minutes <= 0:
        return None
    return db.scalar(
        select(InvDescargaArchivo)
        .where(
            InvDescargaArchivo.tenant_id == tenant_id,
            InvDescargaArchivo.module == module,
            InvDescargaArchivo.request_key == request_key,
            InvDescargaArchivo.state == "success",
            InvDescargaArchivo.gcs_path.is_not(None),
            InvDescargaArchivo.updated_at > _now() - timedelta(minutes=minutes),
        )
        .order_by(InvDescargaArchivo.updated_at.desc())
        .limit(1)
    )


def _user_active_jobs(db: Session, tenant_id: UUID, user_id: UUID, exclude_key: str) -> list[InvDescargaArchivo]:
    rows = db.scalars(
        select(InvDescargaArchivo).where(
            InvDescargaArchivo.tenant_id == tenant_id,
            InvDescargaArchivo.created_by_id == user_id,
            InvDescargaArchivo.state.in_(ACTIVE_STATES),
            (InvDescargaArchivo.request_key.is_(None)) | (InvDescargaArchivo.request_key != exclude_key),
        )
    ).all()
    out = []
    for row in rows:
        if is_stale(row):
            expire_stale(db, row)
        else:
            out.append(row)
    return out


# --- API: pedir / consultar ------------------------------------------------------


def _prepare(spec: ExportSpec, tenant_id: UUID, user, filters: dict[str, Any], export_format: str | None):
    fmt = normalize_format(spec, export_format)
    run_params, key_params = spec.parse(filters or {})
    key = build_request_key(spec.module, tenant_id, key_params, fmt, spec.scope(user))
    return fmt, run_params, key


def lookup_export(db: Session, *, module: str, tenant_id: UUID, user, filters: dict[str, Any], export_format: str | None) -> dict[str, Any]:
    """Sin efectos: ¿hay un trabajo en curso o un archivo reciente para estos filtros?"""
    spec = get_spec(module)
    _fmt, _run, key = _prepare(spec, tenant_id, user, filters, export_format)
    active = _active_for_key(db, tenant_id, spec.module, key)
    db.commit()
    if active is not None:
        return {"status": "active", "job": job_payload(active, user_id=user.id, overlay=live.read_job(active.id))}
    recent = _recent_success(db, tenant_id, spec.module, key)
    if recent is not None:
        return {"status": "available", "job": job_payload(recent, user_id=user.id)}
    return {"status": "none", "job": None}


def request_export(
    db: Session,
    *,
    module: str,
    tenant_id: UUID,
    user,
    filters: dict[str, Any],
    export_format: str | None,
    force_new: bool = False,
) -> dict[str, Any]:
    spec = get_spec(module)
    fmt, run_params, key = _prepare(spec, tenant_id, user, filters, export_format)
    if spec.precheck is not None:
        spec.precheck(db, tenant_id, run_params)

    _advisory_lock(db, tenant_id, spec.module, key)

    active = _active_for_key(db, tenant_id, spec.module, key)
    if active is not None:
        db.commit()
        live.add_subscriber(tenant_id, active.id, user.id)
        payload = job_payload(active, user_id=user.id, overlay=live.read_job(active.id))
        return {"status": "joined", "job": payload}

    if not force_new:
        recent = _recent_success(db, tenant_id, spec.module, key)
        if recent is not None:
            db.commit()
            return {"status": "available", "job": job_payload(recent, user_id=user.id)}

    limit = get_settings().export_max_active_per_user
    mine = _user_active_jobs(db, tenant_id, user.id, key)
    if len(mine) >= limit:
        db.commit()
        busy = job_payload(mine[0], user_id=user.id, overlay=live.read_job(mine[0].id))
        raise ExportLimitError(
            f"Ya tienes una exportación en curso ({busy['label']}, {busy['progress']}%). "
            "Espera a que termine para pedir otra.",
            busy,
        )

    job_id = uuid.uuid4()
    ext = "zip" if fmt == "zip" else fmt
    row = InvDescargaArchivo(
        id=job_id,
        tenant_id=tenant_id,
        module=spec.module,
        filename=f"{spec.module}_{_now().date().isoformat()}.{ext}",
        state="pending",
        progress=0,
        message="En cola…",
        created_by_id=user.id,
        request_key=key,
        errors=[],
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    live.write_job(
        job_id,
        {
            "state": "pending",
            "progress": 0,
            "message": "En cola…",
            "module": spec.module,
            "label": spec.describe(db, tenant_id, run_params) if spec.describe else spec.label,
            "format": fmt,
            "tenant_id": tenant_id,
            "started_by_name": _user_name(db, user.id),
        },
    )
    live.add_subscriber(tenant_id, job_id, user.id)

    try:
        task_id = _dispatch(job_id, tenant_id, spec.module, run_params, fmt)
    except Exception as exc:  # noqa: BLE001
        logger.exception("No se pudo encolar la exportación %s", job_id)
        mark_failure(job_id, tenant_id, f"No se pudo encolar la exportación: {exc}"[:500])
        db.refresh(row)
        return {"status": "queued", "job": job_payload(row, user_id=user.id)}
    if task_id:
        row.celery_task_id = task_id
        db.add(row)
        db.commit()
    return {"status": "queued", "job": job_payload(row, user_id=user.id, overlay=live.read_job(job_id))}


def _dispatch(job_id: UUID, tenant_id: UUID, module: str, params: dict[str, Any], fmt: str) -> str | None:
    settings = get_settings()
    if (settings.export_execution or "celery").strip().lower() == "thread":
        import threading

        from app.modules.exports.runner import run_export_job

        threading.Thread(
            target=run_export_job,
            args=(str(job_id), str(tenant_id), module, params, fmt),
            name=f"export-{job_id}",
            daemon=True,
        ).start()
        return None

    from app.tasks.exports import run_export_task

    queue = (settings.export_celery_queue or "").strip() or None
    result = run_export_task.apply_async(
        args=(str(job_id), str(tenant_id), module, params, fmt),
        queue=queue,
    )
    return result.id


def get_job(db: Session, job_id: UUID, tenant_id: UUID) -> InvDescargaArchivo | None:
    row = db.get(InvDescargaArchivo, job_id)
    if row is None or row.tenant_id != tenant_id:
        return None
    return row


def job_status(db: Session, row: InvDescargaArchivo, user_id: UUID | None) -> dict[str, Any]:
    """Estado leído de Redis; la base solo aporta el registro (una lectura por clave primaria)."""
    if is_stale(row):
        expire_stale(db, row)
        db.commit()
    return job_payload(row, user_id=user_id, overlay=live.read_job(row.id))


def list_my_exports(db: Session, tenant_id: UUID, user_id: UUID, limit: int = 20) -> list[dict[str, Any]]:
    ids = live.my_job_ids(tenant_id, user_id, limit)
    if not ids:
        return []
    uuids = []
    for jid in ids:
        try:
            uuids.append(UUID(jid))
        except ValueError:
            continue
    rows = {
        str(r.id): r
        for r in db.scalars(
            select(InvDescargaArchivo).where(
                InvDescargaArchivo.tenant_id == tenant_id,
                InvDescargaArchivo.id.in_(uuids),
            )
        ).all()
    }
    overlays = live.read_jobs(list(rows.keys()))
    seen = live.seen_ids(tenant_id, user_id)
    out = []
    for jid in ids:
        row = rows.get(jid)
        if row is None:
            continue
        payload = job_payload(row, user_id=user_id, overlay=overlays.get(jid))
        payload["unread"] = payload["state"] in ("success", "failure") and jid not in seen
        out.append(payload)
    return out


# --- Worker: transiciones -----------------------------------------------------------


def _row(db: Session, job_id: UUID, tenant_id: UUID) -> InvDescargaArchivo | None:
    return get_job(db, job_id, tenant_id)


def mark_processing(job_id: UUID, tenant_id: UUID, message: str) -> bool:
    """Devuelve False si el trabajo ya no debe ejecutarse (no existe o terminó)."""
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        row = _row(db, job_id, tenant_id)
        # Si se dio por perdido mientras esperaba en cola, ya hay (o habrá) otro trabajo para la misma clave.
        if row is None or row.state not in ACTIVE_STATES:
            return False
        row.state = "processing"
        row.progress = max(int(row.progress or 0), 2)
        row.message = message
        row.errors = []
        db.add(row)
        db.commit()
        db.refresh(row)
        live.heartbeat(job_id)
        live.write_job(job_id, {"state": "processing", "progress": row.progress, "message": message})
        live.publish(tenant_id, job_id, job_payload(row, overlay=live.read_job(job_id)))
        return True


def touch(job_id: UUID, tenant_id: UUID, progress: int, message: str) -> None:
    """Latido en la base (cada ~minuto) para detectar trabajos colgados aunque Redis no esté."""
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        row = _row(db, job_id, tenant_id)
        if row is None or row.state not in ACTIVE_STATES:
            return
        row.progress = progress
        row.message = message
        row.updated_at = _now()
        db.add(row)
        db.commit()


def mark_success(
    job_id: UUID,
    tenant_id: UUID,
    *,
    filename: str,
    storage_path: str,
    download_url: str,
    expires_at,
    file_size_bytes: int,
    message: str,
) -> None:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        row = _row(db, job_id, tenant_id)
        if row is None:
            return
        row.state = "success"
        row.progress = 100
        row.filename = filename
        row.gcs_path = storage_path
        row.download_url = download_url
        row.expires_at = expires_at
        row.file_size_bytes = file_size_bytes
        row.message = message
        row.errors = []
        db.add(row)
        db.commit()
        db.refresh(row)
        live.write_job(job_id, {"state": "success", "progress": 100, "message": message})
        live.publish(tenant_id, job_id, job_payload(row, overlay=live.read_job(job_id)))


def mark_failure(job_id: UUID, tenant_id: UUID, message: str) -> None:
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        row = _row(db, job_id, tenant_id)
        if row is None:
            return
        row.state = "failure"
        row.progress = 0
        row.message = message
        row.errors = [message]
        db.add(row)
        db.commit()
        db.refresh(row)
        live.write_job(job_id, {"state": "failure", "message": message})
        live.publish(tenant_id, job_id, job_payload(row, overlay=live.read_job(job_id)))


def download_url_for(db: Session, row: InvDescargaArchivo) -> str | None:
    """URL temporal (firmada en GCS, o proxy del API en desarrollo)."""
    from app.core.export_storage import refresh_download_url_if_needed

    if row.state != "success" or not row.gcs_path:
        return None
    url, expires_at = refresh_download_url_if_needed(
        storage_path=row.gcs_path,
        filename=row.filename,
        job_id=row.id,
        current_url=row.download_url,
        expires_at=row.expires_at,
    )
    if url != row.download_url or expires_at != row.expires_at:
        row.download_url = url
        row.expires_at = expires_at
        db.add(row)
        db.commit()
    return url
