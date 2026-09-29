"""API unificada de exportaciones: pedir, consultar, avisos del usuario y eventos en vivo (SSE)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_id
from app.db.session import SessionLocal, get_db
from app.modules.exports import live, service
from app.modules.exports.specs import SPECS, get_spec
from app.modules.iam.dependencies import _has_action
from app.modules.iam.models import User
from app.modules.tenants.features import is_feature_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exports", tags=["exports"])

SSE_PING_SECONDS = 20


class ExportRequestBody(BaseModel):
    format: str | None = Field(default=None, description="csv | xlsx | zip (según la exportación)")
    filters: dict[str, Any] = Field(default_factory=dict)
    force_new: bool = Field(default=False, description="Generar aunque haya un archivo reciente")


class ExportJob(BaseModel):
    job_id: str
    module: str
    label: str
    format: str
    state: str
    progress: int = 0
    message: str = ""
    filename: str | None = None
    file_size_bytes: int | None = None
    rows_done: int | None = None
    rows_total: int | None = None
    created_at: str | None = None
    finished_at: str | None = None
    started_by_me: bool = False
    started_by_name: str | None = None
    errors: list[str] = Field(default_factory=list)
    unread: bool = False


class ExportRequestResult(BaseModel):
    status: Literal["queued", "joined", "available", "active", "none"]
    job: ExportJob | None = None


class SeenBody(BaseModel):
    job_ids: list[str] = Field(default_factory=list)


def _check_permission(db: Session, user: User, tenant_id: UUID, module: str) -> None:
    try:
        spec = get_spec(module)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    code, action = spec.permission
    if not is_feature_enabled(db, tenant_id, code):
        raise HTTPException(status_code=403, detail="Módulo no habilitado para este tenant")
    if not _has_action(user, db, tenant_id, code, action):  # type: ignore[arg-type]
        raise HTTPException(status_code=403, detail="No tiene permiso para exportar este módulo")


@router.get("/modules")
def export_modules(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    """Exportaciones disponibles para el usuario (etiqueta y formatos)."""
    out = []
    for spec in SPECS.values():
        code, action = spec.permission
        if is_feature_enabled(db, tenant_id, code) and _has_action(user, db, tenant_id, code, action):  # type: ignore[arg-type]
            out.append({"module": spec.module, "label": spec.label, "formats": list(spec.formats)})
    return out


@router.get("/mine", response_model=list[ExportJob])
def my_exports(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    """Exportaciones que el usuario pidió o a las que se sumó (campanita)."""
    return service.list_my_exports(db, tenant_id, user.id)


@router.post("/mine/seen")
def mark_exports_seen(
    body: SeenBody,
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    live.mark_seen(tenant_id, user.id, [j for j in body.job_ids if j][:100])
    return {"success": True}


@router.delete("/mine/{job_id}")
def forget_export(
    job_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    live.forget(tenant_id, user.id, str(job_id))
    return {"success": True}


@router.get("/jobs/{job_id}", response_model=ExportJob)
def export_job_status(
    job_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    """Estado del trabajo. El avance se lee de Redis; la base solo aporta el registro por clave primaria."""
    row = service.get_job(db, job_id, tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Exportación no encontrada")
    _check_permission(db, user, tenant_id, row.module)
    return service.job_status(db, row, user.id)


@router.get("/jobs/{job_id}/download")
def export_job_download(
    job_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    """Enlace temporal de descarga (URL firmada de almacenamiento; el archivo no pasa por el API)."""
    row = service.get_job(db, job_id, tenant_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Exportación no encontrada")
    _check_permission(db, user, tenant_id, row.module)
    url = service.download_url_for(db, row)
    if not url:
        raise HTTPException(status_code=409, detail="El archivo todavía no está listo")
    live.mark_seen(tenant_id, user.id, [str(row.id)])
    return {"url": url, "filename": row.filename, "file_size_bytes": row.file_size_bytes}


@router.post("/{module}/lookup", response_model=ExportRequestResult)
def export_lookup(
    module: str,
    body: ExportRequestBody,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    """Sin efectos: indica si hay un trabajo en curso o un archivo reciente para estos filtros."""
    _check_permission(db, user, tenant_id, module)
    try:
        return service.lookup_export(
            db, module=module, tenant_id=tenant_id, user=user, filters=body.filters, export_format=body.format
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/{module}", response_model=ExportRequestResult)
def export_request(
    module: str,
    body: ExportRequestBody,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    """Pide una exportación: se encola, se suma a la que ya está en curso o se ofrece un archivo reciente."""
    _check_permission(db, user, tenant_id, module)
    try:
        return service.request_export(
            db,
            module=module,
            tenant_id=tenant_id,
            user=user,
            filters=body.filters,
            export_format=body.format,
            force_new=body.force_new,
        )
    except service.ExportLimitError as exc:
        return JSONResponse(status_code=429, content={"detail": str(exc), "job": exc.job})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# --- Eventos en vivo (Server-Sent Events) --------------------------------------------


def _authenticate(headers: dict[str, str | None]) -> tuple[UUID, UUID]:
    """Autentica con una sesión corta: la conexión SSE no retiene conexiones a la base."""
    with SessionLocal() as db:
        tenant_id = get_tenant_id(
            db=db,
            host=headers.get("host"),
            x_forwarded_host=headers.get("x-forwarded-host"),
            x_tenant_id=headers.get("x-tenant-id"),
            x_tenant_slug=headers.get("x-tenant-slug"),
        )
        user = get_current_user(db=db, tenant_id=tenant_id, authorization=headers.get("authorization"))
        return tenant_id, user.id


@router.get("/events")
async def export_events(
    request: Request,
    authorization: str | None = Header(default=None),
):
    """Progreso y avisos de las exportaciones del usuario, empujados por el servidor.

    El worker publica en Redis Pub/Sub y este endpoint lo reenvía; no se consulta la base. El navegador
    reconecta solo; si Redis no está disponible responde 503 y el cliente pasa a polling.
    """
    headers = {k.lower(): v for k, v in request.headers.items()}
    headers["authorization"] = authorization
    tenant_id, user_id = await run_in_threadpool(_authenticate, headers)

    try:
        from redis import asyncio as aioredis

        redis = aioredis.from_url(
            live.redis_url(), decode_responses=True, socket_connect_timeout=2, protocol=2
        )
        pubsub = redis.pubsub()
        await pubsub.subscribe(live.user_channel(tenant_id, user_id))
    except Exception:  # noqa: BLE001
        logger.warning("SSE de exportaciones sin Redis", exc_info=True)
        raise HTTPException(status_code=503, detail="Eventos en vivo no disponibles") from None

    async def stream():
        try:
            yield "retry: 5000\n\n"
            yield f"event: ready\ndata: {json.dumps({'ok': True})}\n\n"
            idle = 0.0
            while True:
                if await request.is_disconnected():
                    break
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    idle = 0.0
                    yield f"data: {message['data']}\n\n"
                    continue
                idle += 1.0
                if idle >= SSE_PING_SECONDS:
                    idle = 0.0
                    # Mantiene viva la conexión a través de proxies/balanceadores.
                    yield ": ping\n\n"
                await asyncio.sleep(0)
        finally:
            try:
                await pubsub.unsubscribe()
                await pubsub.aclose()
                await redis.aclose()
            except Exception:  # noqa: BLE001
                pass

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
