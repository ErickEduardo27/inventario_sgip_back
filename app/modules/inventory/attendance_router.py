"""Rutas REST de asistencia."""

from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db, get_tenant_id
from app.modules.iam.dependencies import require_permission
from app.modules.iam.models import User
from app.modules.inventory import attendance_service as att
from app.modules.inventory.attendance_schemas import (
    AttendanceAssignmentsWrite,
    AttendanceGeofencePreview,
    AttendanceLocationSampleWrite,
    AttendanceMarkWrite,
    AttendanceSessionListResponse,
)

router = APIRouter(prefix="/attendance", tags=["attendance"])


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


@router.get("/establishments")
def attendance_establishments(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
    _: User = Depends(require_permission("asistencia", "view")),
):
    return {"data": att.list_user_establishments(db, tenant_id, user.id)}


@router.get("/me/session")
def attendance_my_session(
    establishment_id: int = Query(...),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
    _: User = Depends(require_permission("asistencia", "view")),
):
    try:
        return att.get_my_session_state(db, tenant_id, user, establishment_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/geofence/preview")
def attendance_geofence_preview(
    body: AttendanceGeofencePreview,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
    _: User = Depends(require_permission("asistencia", "view")),
):
    try:
        return att.preview_geofence(
            db,
            tenant_id,
            user.id,
            body.establishment_id,
            body.latitude,
            body.longitude,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/marks")
def attendance_create_mark(
    body: AttendanceMarkWrite,
    request: Request,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
    _: User = Depends(require_permission("asistencia", "create")),
):
    try:
        return att.create_mark(
            db,
            tenant_id,
            user,
            establishment_id=body.establishment_id,
            mark_type=body.mark_type,
            latitude=body.latitude,
            longitude=body.longitude,
            accuracy_m=body.accuracy_m,
            ip_address=_client_ip(request),
            user_agent=request.headers.get("User-Agent"),
            device_info=body.device_info,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/location-samples")
def attendance_location_sample(
    body: AttendanceLocationSampleWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
    _: User = Depends(require_permission("asistencia", "create")),
):
    try:
        return att.add_location_sample(
            db,
            tenant_id,
            user.id,
            session_id=body.session_id,
            latitude=body.latitude,
            longitude=body.longitude,
            accuracy_m=body.accuracy_m,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/panel/sessions", response_model=AttendanceSessionListResponse)
def attendance_panel_sessions(
    work_date: date | None = Query(None),
    user_id: UUID | None = Query(None),
    establishment_id: int | None = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("panel_asistencia", "view")),
):
    rows, total = att.list_panel_sessions(
        db,
        tenant_id,
        work_date=work_date,
        user_id=user_id,
        establishment_id=establishment_id,
        page=page,
        per_page=per_page,
    )
    pages = max(1, (total + per_page - 1) // per_page)
    return AttendanceSessionListResponse(
        data=rows,
        meta={"page": page, "per_page": per_page, "total": total, "pages": pages},
    )


@router.get("/panel/sessions/{session_id}")
def attendance_panel_session_detail(
    session_id: int,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("panel_asistencia", "view")),
):
    try:
        return att.get_panel_session_detail(db, tenant_id, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/panel/users/{user_id}/assignments")
def attendance_panel_user_assignments(
    user_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("panel_asistencia", "view")),
):
    return {"establishment_ids": att.list_user_assignments(db, tenant_id, user_id)}


@router.put("/panel/users/{user_id}/assignments")
def attendance_panel_set_assignments(
    user_id: UUID,
    body: AttendanceAssignmentsWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(require_permission("panel_asistencia", "edit")),
):
    if body.user_id != user_id:
        raise HTTPException(status_code=400, detail="user_id inconsistente")
    try:
        return att.set_user_assignments(db, tenant_id, user_id, body.establishment_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
