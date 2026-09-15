"""Rutas REST para la app móvil de brigadas."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_tenant_id
from app.modules.iam.dependencies import require_permission
from app.modules.iam.models import User
from app.modules.inventory import mobile_service as mob
from app.modules.inventory.mobile_schemas import (
    MobileEnsureCardRequest,
    MobileIdentifyRequest,
    MobileLocationPing,
    MobileSyncRequest,
)

router = APIRouter(prefix="/mobile", tags=["mobile"])


@router.get("/bootstrap")
def mobile_bootstrap(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(require_permission("hoja_captura", "view")),
):
    return mob.bootstrap(db, tenant_id, user)


@router.get("/cards")
def mobile_cards(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    search: str | None = Query(None),
    flag_firma: bool | None = Query(None),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("hoja_captura", "view")),
):
    """Lista las hojas de captura igual que el front (`/cards/records`)."""
    from app.modules.inventory import service as inv
    from app.modules.inventory.schemas import RecordQuery

    q = RecordQuery(
        page=page,
        per_page=per_page,
        column="hoj_num",
        search=search,
        flag_firma=flag_firma,
        ord_tipo="asc",
    )
    rows, total = inv.list_cards(db, tenant_id, q, {"hoj_num", "state", "nota_interna"})
    return {"data": rows, "meta": inv.paged_meta(total, q.page, q.per_page)}


@router.get("/catalog")
def mobile_catalog(
    page: int = Query(1, ge=1),
    per_page: int = Query(400, ge=20, le=800),
    search: str | None = Query(None),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("hoja_captura", "view")),
):
    return mob.catalog_index(db, tenant_id, page=page, per_page=per_page, search=search)


@router.get("/lookup/{valor}")
def mobile_lookup(
    valor: str,
    tipo: str | None = Query(None, description="M | S | A | R | SE. Vacío = probar todos."),
    environment_id: int | None = Query(None),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(require_permission("hoja_captura", "view")),
):
    return mob.lookup_code(db, tenant_id, user, valor, tipo, environment_id)


@router.post("/identify")
def mobile_identify(
    body: MobileIdentifyRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("hoja_captura", "view")),
):
    return mob.identify(db, tenant_id, body)


@router.post("/cards/ensure")
def mobile_ensure_card(
    body: MobileEnsureCardRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(require_permission("hoja_captura", "create")),
):
    try:
        return mob.ensure_open_card(db, tenant_id, user, body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/sync")
def mobile_sync(
    body: MobileSyncRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(require_permission("hoja_captura", "create")),
):
    return mob.sync_batch(db, tenant_id, user, body)


@router.get("/brigade")
def mobile_brigade(
    establishment_id: int | None = Query(None),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(require_permission("hoja_captura", "view")),
):
    return mob.brigade_stats(db, tenant_id, user, establishment_id)


@router.post("/location")
def mobile_location(
    body: MobileLocationPing,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    """Geolocalización del levantamiento. Reutiliza asistencia si hay sesión."""
    from app.modules.inventory import attendance_service as att

    try:
        preview = att.preview_geofence(
            db, tenant_id, user.id, body.establishment_id, body.latitude, body.longitude
        )
    except ValueError:
        preview = {
            "geofence_valid": True,
            "distance_m": None,
            "status": "SIN_ASIGNACION",
            "within_label": "Local sin restricción de geocerca para este usuario",
        }
    if body.session_id:
        try:
            att.add_location_sample(
                db,
                tenant_id,
                user.id,
                session_id=body.session_id,
                latitude=body.latitude,
                longitude=body.longitude,
                accuracy_m=body.accuracy_m,
            )
        except ValueError:
            pass
    return preview
