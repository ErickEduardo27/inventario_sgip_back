"""Lógica de asistencia, geocerca y productividad."""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.modules.iam.models import User
from app.modules.inventory import models as m
from app.modules.inventory.attendance_models import (
    InvAttendanceLocationSample,
    InvAttendanceMark,
    InvAttendanceSession,
    InvUserEstablishmentAssignment,
)

LIMA_TZ = ZoneInfo("America/Lima")

MARK_TYPES = frozenset(
    {"entrada", "inicio_inventario", "pausa", "regreso", "fin_jornada"}
)

MARK_LABELS = {
    "entrada": "Entrada",
    "inicio_inventario": "Inicio inventario",
    "pausa": "Pausa",
    "regreso": "Regreso",
    "fin_jornada": "Fin de jornada",
}


def _today_lima() -> date:
    return datetime.now(LIMA_TZ).date()


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def evaluate_geofence(
    est: m.InvEstablishment,
    latitude: float,
    longitude: float,
) -> tuple[bool, float | None, str]:
    if est.latitude is None or est.longitude is None:
        return True, None, "SIN_COORDENADAS"
    dist = haversine_m(latitude, longitude, est.latitude, est.longitude)
    radius = est.geofence_radius_m or 100
    if dist <= radius:
        return True, dist, "PRESENTE"
    return False, dist, "FUERA_DEL_AREA"


def _establishment_row(est: m.InvEstablishment) -> dict[str, Any]:
    return {
        "id": int(est.id),
        "code": est.code,
        "description": est.description,
        "address": est.address or est.trade_address,
        "latitude": est.latitude,
        "longitude": est.longitude,
        "geofence_radius_m": est.geofence_radius_m or 100,
    }


def list_user_establishments(db: Session, tenant_id: UUID, user_id: UUID) -> list[dict[str, Any]]:
    assigned_ids = db.scalars(
        select(InvUserEstablishmentAssignment.establishment_id).where(
            InvUserEstablishmentAssignment.tenant_id == tenant_id,
            InvUserEstablishmentAssignment.user_id == user_id,
        )
    ).all()
    q = select(m.InvEstablishment).where(m.InvEstablishment.tenant_id == tenant_id)
    if assigned_ids:
        q = q.where(m.InvEstablishment.id.in_(assigned_ids))
    q = q.order_by(m.InvEstablishment.description.asc())
    return [_establishment_row(e) for e in db.scalars(q).all()]


def preview_geofence(
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
    establishment_id: int,
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    est = _get_establishment(db, tenant_id, establishment_id)
    _assert_establishment_access(db, tenant_id, user_id, establishment_id)
    valid, dist, status = evaluate_geofence(est, latitude, longitude)
    return {
        "establishment": _establishment_row(est),
        "geofence_valid": valid,
        "distance_m": round(dist, 1) if dist is not None else None,
        "status": status,
        "within_label": "Dentro del establecimiento" if valid and status == "PRESENTE" else (
            "Establecimiento sin coordenadas GPS" if status == "SIN_COORDENADAS" else "Fuera del área permitida"
        ),
    }


def _get_establishment(db: Session, tenant_id: UUID, establishment_id: int) -> m.InvEstablishment:
    est = db.get(m.InvEstablishment, establishment_id)
    if not est or est.tenant_id != tenant_id:
        raise ValueError("No se encontró el establecimiento.")
    return est


def _assert_establishment_access(
    db: Session, tenant_id: UUID, user_id: UUID, establishment_id: int
) -> None:
    assigned = db.scalar(
        select(func.count())
        .select_from(InvUserEstablishmentAssignment)
        .where(
            InvUserEstablishmentAssignment.tenant_id == tenant_id,
            InvUserEstablishmentAssignment.user_id == user_id,
        )
    )
    if not assigned:
        return
    ok = db.scalar(
        select(func.count())
        .select_from(InvUserEstablishmentAssignment)
        .where(
            InvUserEstablishmentAssignment.tenant_id == tenant_id,
            InvUserEstablishmentAssignment.user_id == user_id,
            InvUserEstablishmentAssignment.establishment_id == establishment_id,
        )
    )
    if not ok:
        raise ValueError("El establecimiento no está asignado a su usuario.")


def _get_open_session(
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
    establishment_id: int,
    work_date: date | None = None,
) -> InvAttendanceSession | None:
    wd = work_date or _today_lima()
    return db.scalar(
        select(InvAttendanceSession)
        .options(selectinload(InvAttendanceSession.marks))
        .where(
            InvAttendanceSession.tenant_id == tenant_id,
            InvAttendanceSession.user_id == user_id,
            InvAttendanceSession.establishment_id == establishment_id,
            InvAttendanceSession.work_date == wd,
        )
    )


def _mark_to_dict(mark: InvAttendanceMark) -> dict[str, Any]:
    return {
        "id": int(mark.id),
        "mark_type": mark.mark_type,
        "mark_label": MARK_LABELS.get(mark.mark_type, mark.mark_type),
        "marked_at": mark.marked_at.isoformat() if mark.marked_at else None,
        "latitude": mark.latitude,
        "longitude": mark.longitude,
        "accuracy_m": mark.accuracy_m,
        "distance_m": mark.distance_m,
        "geofence_valid": mark.geofence_valid,
        "status": mark.status,
    }


def _session_to_dict(session: InvAttendanceSession, est: m.InvEstablishment | None = None) -> dict[str, Any]:
    d: dict[str, Any] = {
        "id": int(session.id),
        "work_date": session.work_date.isoformat(),
        "status": session.status,
        "inventory_active": session.inventory_active,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "ended_at": session.ended_at.isoformat() if session.ended_at else None,
        "establishment_id": int(session.establishment_id),
        "marks": [_mark_to_dict(x) for x in (session.marks or [])],
    }
    if est:
        d["establishment"] = _establishment_row(est)
    return d


def get_my_session_state(
    db: Session,
    tenant_id: UUID,
    user: User,
    establishment_id: int,
) -> dict[str, Any]:
    _assert_establishment_access(db, tenant_id, user.id, establishment_id)
    est = _get_establishment(db, tenant_id, establishment_id)
    session = _get_open_session(db, tenant_id, user.id, establishment_id)
    items_today = _count_items_for_user_today(db, tenant_id, user.id)
    out: dict[str, Any] = {
        "user": {"id": str(user.id), "full_name": user.full_name, "email": user.email},
        "work_date": _today_lima().isoformat(),
        "establishment": _establishment_row(est),
        "session": _session_to_dict(session, est) if session else None,
        "items_inventoried_today": items_today,
        "allowed_marks": _allowed_next_marks(session),
    }
    return out


def _allowed_next_marks(session: InvAttendanceSession | None) -> list[str]:
    if session is None or session.status == "cerrada":
        return ["entrada"]
    types = [m.mark_type for m in (session.marks or [])]
    if session.inventory_active:
        if types and types[-1] == "pausa":
            return ["regreso", "fin_jornada"]
        return ["pausa", "fin_jornada"]
    if "entrada" in types and "inicio_inventario" not in types:
        return ["inicio_inventario", "fin_jornada"]
    if "entrada" in types:
        return ["inicio_inventario", "fin_jornada"]
    return ["entrada"]


def _validate_mark_sequence(session: InvAttendanceSession | None, mark_type: str) -> None:
    allowed = _allowed_next_marks(session)
    if mark_type not in allowed:
        labels = ", ".join(MARK_LABELS.get(t, t) for t in allowed)
        raise ValueError(f"Marcación no permitida en este momento. Opciones: {labels}")


def create_mark(
    db: Session,
    tenant_id: UUID,
    user: User,
    *,
    establishment_id: int,
    mark_type: str,
    latitude: float,
    longitude: float,
    accuracy_m: float | None,
    ip_address: str | None,
    user_agent: str | None,
    device_info: str | None,
) -> dict[str, Any]:
    if mark_type not in MARK_TYPES:
        raise ValueError("Tipo de marcación no válido.")

    est = _get_establishment(db, tenant_id, establishment_id)
    _assert_establishment_access(db, tenant_id, user.id, establishment_id)

    work_date = _today_lima()
    session = _get_open_session(db, tenant_id, user.id, establishment_id, work_date)

    if mark_type == "entrada" and session and session.status == "cerrada":
        raise ValueError("La jornada de hoy ya fue cerrada.")

    _validate_mark_sequence(session if session and session.status != "cerrada" else None, mark_type)

    geofence_valid, distance_m, status = evaluate_geofence(est, latitude, longitude)
    now = datetime.now(timezone.utc)

    if session is None:
        session = InvAttendanceSession(
            tenant_id=tenant_id,
            user_id=user.id,
            establishment_id=establishment_id,
            work_date=work_date,
            status="abierta",
            inventory_active=False,
        )
        db.add(session)
        db.flush()

    mark = InvAttendanceMark(
        tenant_id=tenant_id,
        session_id=int(session.id),
        user_id=user.id,
        establishment_id=establishment_id,
        mark_type=mark_type,
        marked_at=now,
        latitude=latitude,
        longitude=longitude,
        accuracy_m=accuracy_m,
        distance_m=round(distance_m, 1) if distance_m is not None else None,
        geofence_valid=geofence_valid,
        status=status,
        ip_address=ip_address,
        user_agent=(user_agent or "")[:2000] or None,
        device_info=(device_info or "")[:500] or None,
    )
    db.add(mark)

    if mark_type == "entrada" and session.started_at is None:
        session.started_at = now
    if mark_type == "inicio_inventario":
        session.inventory_active = True
    if mark_type == "pausa":
        session.inventory_active = False
    if mark_type == "regreso":
        session.inventory_active = True
    if mark_type == "fin_jornada":
        session.inventory_active = False
        session.status = "cerrada"
        session.ended_at = now

    db.commit()
    session = db.scalar(
        select(InvAttendanceSession)
        .options(selectinload(InvAttendanceSession.marks))
        .where(InvAttendanceSession.id == session.id)
    )

    return {
        "success": True,
        "message": f"Marcación registrada: {MARK_LABELS.get(mark_type, mark_type)}",
        "geofence_valid": geofence_valid,
        "status": status,
        "mark": _mark_to_dict(mark),
        "session": _session_to_dict(session, est) if session else None,
    }


def add_location_sample(
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
    *,
    session_id: int,
    latitude: float,
    longitude: float,
    accuracy_m: float | None,
) -> dict[str, Any]:
    session = db.get(InvAttendanceSession, session_id)
    if not session or session.tenant_id != tenant_id or session.user_id != user_id:
        raise ValueError("Jornada no encontrada.")
    if session.status != "abierta" or not session.inventory_active:
        raise ValueError("Solo se registran ubicaciones durante inventario activo.")

    sample = InvAttendanceLocationSample(
        tenant_id=tenant_id,
        session_id=session_id,
        latitude=latitude,
        longitude=longitude,
        accuracy_m=accuracy_m,
    )
    db.add(sample)
    db.commit()
    return {"success": True, "message": "Ubicación registrada"}


def _count_items_for_user_today(db: Session, tenant_id: UUID, user_id: UUID) -> int:
    today = _today_lima()
    start = datetime.combine(today, datetime.min.time()).replace(tzinfo=LIMA_TZ)
    end = start + timedelta(days=1)
    return int(
        db.scalar(
            select(func.count())
            .select_from(m.InvItemRegistrationLog)
            .where(
                m.InvItemRegistrationLog.tenant_id == tenant_id,
                m.InvItemRegistrationLog.user_id == user_id,
                m.InvItemRegistrationLog.created_at >= start,
                m.InvItemRegistrationLog.created_at < end,
            )
        )
        or 0
    )


def _count_items_between(
    db: Session, tenant_id: UUID, user_id: UUID, start: datetime, end: datetime
) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(m.InvItemRegistrationLog)
            .where(
                m.InvItemRegistrationLog.tenant_id == tenant_id,
                m.InvItemRegistrationLog.user_id == user_id,
                m.InvItemRegistrationLog.created_at >= start,
                m.InvItemRegistrationLog.created_at <= end,
            )
        )
        or 0
    )


def _compute_worked_minutes(marks: list[InvAttendanceMark]) -> int:
    if not marks:
        return 0
    sorted_marks = sorted(marks, key=lambda x: x.marked_at)
    entrada = next((m for m in sorted_marks if m.mark_type == "entrada"), None)
    fin = next((m for m in reversed(sorted_marks) if m.mark_type == "fin_jornada"), None)
    if not entrada:
        return 0
    end = fin.marked_at if fin else sorted_marks[-1].marked_at
    total = (end - entrada.marked_at).total_seconds()
    pause_start: datetime | None = None
    paused = 0.0
    for mk in sorted_marks:
        if mk.mark_type == "pausa":
            pause_start = mk.marked_at
        elif mk.mark_type == "regreso" and pause_start:
            paused += (mk.marked_at - pause_start).total_seconds()
            pause_start = None
    return max(0, int((total - paused) / 60))


def _session_productivity(
    db: Session, tenant_id: UUID, session: InvAttendanceSession, marks: list[InvAttendanceMark]
) -> dict[str, Any]:
    entrada = next((m for m in marks if m.mark_type == "entrada"), None)
    fin = next((m for m in marks if m.mark_type == "fin_jornada"), None)
    inicio_inv = next((m for m in marks if m.mark_type == "inicio_inventario"), None)
    items = 0
    if entrada:
        end = fin.marked_at if fin else datetime.now(timezone.utc)
        items = _count_items_between(db, tenant_id, session.user_id, entrada.marked_at, end)
    worked_min = _compute_worked_minutes(marks)
    hours = worked_min / 60 if worked_min else 0
    avg = round(items / hours, 1) if hours > 0 else None
    return {
        "items_inventoried": items,
        "worked_minutes": worked_min,
        "worked_hours_label": f"{worked_min // 60}h {worked_min % 60}m",
        "avg_items_per_hour": avg,
        "inicio_inventario_at": inicio_inv.marked_at.isoformat() if inicio_inv else None,
    }


def list_panel_sessions(
    db: Session,
    tenant_id: UUID,
    *,
    work_date: date | None = None,
    user_id: UUID | None = None,
    establishment_id: int | None = None,
    page: int = 1,
    per_page: int = 20,
) -> tuple[list[dict[str, Any]], int]:
    filters = [InvAttendanceSession.tenant_id == tenant_id]
    if work_date:
        filters.append(InvAttendanceSession.work_date == work_date)
    if user_id:
        filters.append(InvAttendanceSession.user_id == user_id)
    if establishment_id:
        filters.append(InvAttendanceSession.establishment_id == establishment_id)

    total = int(
        db.scalar(select(func.count()).select_from(InvAttendanceSession).where(*filters)) or 0
    )
    rows = db.scalars(
        select(InvAttendanceSession)
        .where(*filters)
        .order_by(InvAttendanceSession.work_date.desc(), InvAttendanceSession.started_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    ).all()

    user_ids = {s.user_id for s in rows}
    est_ids = {s.establishment_id for s in rows}
    users = {
        u.id: u
        for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()
    } if user_ids else {}
    ests = {
        int(e.id): e
        for e in db.scalars(
            select(m.InvEstablishment).where(m.InvEstablishment.id.in_(est_ids))
        ).all()
    } if est_ids else {}

    out: list[dict[str, Any]] = []
    for s in rows:
        marks = db.scalars(
            select(InvAttendanceMark)
            .where(InvAttendanceMark.session_id == s.id)
            .order_by(InvAttendanceMark.marked_at.asc())
        ).all()
        prod = _session_productivity(db, tenant_id, s, list(marks))
        u = users.get(s.user_id)
        est = ests.get(int(s.establishment_id))
        out.append(
            {
                "id": int(s.id),
                "work_date": s.work_date.isoformat(),
                "status": s.status,
                "inventory_active": s.inventory_active,
                "started_at": s.started_at.isoformat() if s.started_at else None,
                "ended_at": s.ended_at.isoformat() if s.ended_at else None,
                "user_id": str(s.user_id),
                "user_name": u.full_name if u else "—",
                "user_email": u.email if u else "—",
                "establishment_id": int(s.establishment_id),
                "establishment_name": est.description if est else "—",
                "establishment_code": est.code if est else "—",
                "marks_count": len(marks),
                **prod,
            }
        )
    return out, int(total)


def get_panel_session_detail(db: Session, tenant_id: UUID, session_id: int) -> dict[str, Any]:
    session = db.get(InvAttendanceSession, session_id)
    if not session or session.tenant_id != tenant_id:
        raise ValueError("Jornada no encontrada.")
    marks = db.scalars(
        select(InvAttendanceMark)
        .where(InvAttendanceMark.session_id == session_id)
        .order_by(InvAttendanceMark.marked_at.asc())
    ).all()
    samples = db.scalars(
        select(InvAttendanceLocationSample)
        .where(InvAttendanceLocationSample.session_id == session_id)
        .order_by(InvAttendanceLocationSample.sampled_at.asc())
    ).all()
    user = db.get(User, session.user_id)
    est = db.get(m.InvEstablishment, session.establishment_id)
    prod = _session_productivity(db, tenant_id, session, list(marks))
    return {
        **_session_to_dict(session, est),
        "user": {"id": str(session.user_id), "full_name": user.full_name if user else "—", "email": user.email if user else ""},
        "marks": [_mark_to_dict(mk) for mk in marks],
        "location_samples": [
            {
                "latitude": s.latitude,
                "longitude": s.longitude,
                "accuracy_m": s.accuracy_m,
                "sampled_at": s.sampled_at.isoformat(),
            }
            for s in samples
        ],
        "productivity": prod,
    }


def set_user_assignments(
    db: Session,
    tenant_id: UUID,
    user_id: UUID,
    establishment_ids: list[int],
) -> dict[str, Any]:
    db.execute(
        InvUserEstablishmentAssignment.__table__.delete().where(
            InvUserEstablishmentAssignment.tenant_id == tenant_id,
            InvUserEstablishmentAssignment.user_id == user_id,
        )
    )
    for eid in establishment_ids:
        est = _get_establishment(db, tenant_id, eid)
        _ = est
        db.add(
            InvUserEstablishmentAssignment(
                tenant_id=tenant_id,
                user_id=user_id,
                establishment_id=eid,
            )
        )
    db.commit()
    return {"success": True, "message": "Asignaciones actualizadas", "count": len(establishment_ids)}


def list_user_assignments(db: Session, tenant_id: UUID, user_id: UUID) -> list[int]:
    return [
        int(x)
        for x in db.scalars(
            select(InvUserEstablishmentAssignment.establishment_id).where(
                InvUserEstablishmentAssignment.tenant_id == tenant_id,
                InvUserEstablishmentAssignment.user_id == user_id,
            )
        ).all()
    ]
