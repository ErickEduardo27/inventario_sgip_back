"""Lógica de negocio equivalente a controladores tenant de SAP-GrupoISO (Laravel)."""

from __future__ import annotations

import calendar
import math
import uuid as uuid_mod
from datetime import date, datetime, time, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import asc, desc, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.core.inventory_numbers import (
    format_hoj_num,
    format_inv_num,
    numeric_column_filter,
    numeric_column_ilike,
    parse_inventory_number,
    try_parse_inventory_number,
)
from app.core.timezone import day_end_pe, day_start_pe, enrich_pe_timestamps, format_datetime_pe
from app.modules.inventory import geo_catalog as geo
from app.modules.inventory import models as m
from app.modules.iam.models import User
from app.modules.inventory.schemas import (
    AuditLogQuery,
    CardItemWrite,
    CardWrite,
    CostCenterWrite,
    EnvironmentWrite,
    EstablishmentWrite,
    InventoryNumWrite,
    ItemCardTranslate,
    ListSbnWrite,
    MargesiWrite,
    PersonWrite,
    RecordQuery,
    UserInventoryConf,
)
from app.modules.templates.header_image import decode_template_header_upload


def _ord_clause(model: type, column_name: str, ord_tipo: str):
    col = getattr(model, column_name, None)
    if col is None:
        col = model.id
    return desc(col) if str(ord_tipo).lower() == "desc" else asc(col)


def _paged(session: Session, stmt, page: int, per_page: int) -> tuple[list[Any], int]:
    total = session.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = session.scalars(stmt.offset((page - 1) * per_page).limit(per_page)).all()
    return list(rows), int(total)


def _search_like(q: RecordQuery) -> str | None:
    term = (q.search or "").strip()
    if term:
        return f"%{term}%"
    return None


_CARD_INT_FILTER_COLS = frozenset({"hoj_num", "state", "hoj_can_tot"})
_ITEMCARD_INT_FILTER_COLS = frozenset({"inv_num", "id_card", "id"})
_AUDIT_INT_FILTER_COLS = frozenset({"itemcard_id", "card_id"})


def _where_column_ilike(model: type, col_name: str, value: str, *, numeric_cols: frozenset[str]) -> Any:
    col = getattr(model, col_name)
    if col_name in numeric_cols:
        return numeric_column_filter(col, value)
    return col.ilike(f"%{value}%")


def row_to_dict(obj: Any) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in obj.__mapper__.c.keys():
        v = getattr(obj, k)
        if isinstance(v, UUID):
            v = str(v)
        elif hasattr(v, "isoformat"):
            v = v.isoformat()
        out[k] = v
    return out


def inventory_row_dict(obj: Any) -> dict[str, Any]:
    """Serialización de hoja/bien con fechas legibles en hora de Perú."""
    return enrich_pe_timestamps(row_to_dict(obj))


_PHOTO_WRITE_EXCLUDE = frozenset({"id", "photo_base64", "photo_clear", "photo_mime"})


def _digits_only(value: object) -> str:
    return "".join(ch for ch in str(value or "").strip() if ch.isdigit())


def _pad_geo_id(value: object | None, length: int) -> str | None:
    digits = _digits_only(value) if value is not None else ""
    if not digits:
        return None
    if len(digits) > length:
        return digits[:length]
    return digits.zfill(length)


def _establishment_geo_public(
    department_id: object | None,
    province_id: object | None,
    district_id: object | None,
) -> tuple[str | None, str | None, str | None]:
    """IDs geográficos normalizados (2/4/6 dígitos) y derivados desde ubigeo/distrito."""
    district_id = _pad_geo_id(district_id, 6)
    province_id = _pad_geo_id(province_id, 4)
    department_id = _pad_geo_id(department_id, 2)
    if district_id:
        if not province_id:
            province_id = district_id[:4]
        if not department_id:
            department_id = district_id[:2]
    if province_id and not department_id:
        department_id = province_id[:2]
    return department_id, province_id, district_id


def establishment_row_public_dict(row: m.InvEstablishment) -> dict[str, Any]:
    """Serialización de local sin incluir el binario de la foto."""
    d = row_to_dict(row)
    d.pop("photo_blob", None)
    dept, prov, dist = _establishment_geo_public(
        d.get("department_id"),
        d.get("province_id"),
        d.get("district_id"),
    )
    d["department_id"] = dept
    d["province_id"] = prov
    d["district_id"] = dist
    return d


def _apply_establishment_photo(row: m.InvEstablishment, body: EstablishmentWrite) -> None:
    if body.photo_clear:
        row.photo_blob = None
        row.photo_mime = None
        row.photo_token = None
        return
    b64 = (body.photo_base64 or "").strip()
    if not b64:
        return
    try:
        raw, mime = decode_template_header_upload(b64, body.photo_mime)
    except AppError as e:
        raise ValueError(e.message) from e
    row.photo_blob = raw
    row.photo_mime = mime
    row.photo_token = uuid_mod.uuid4()


# --- Establecimientos (LocalesController store / BienesController store duplicate) ---


def _normalize_geo_ids(
    country_id: str | None,
    department_id: str | None,
    province_id: str | None,
    district_id: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Asegura NULL en BD (no cadena vacía), padding de IDs y coherencia jerárquica."""
    country = (country_id or "").strip() or None
    dept, prov, dist = _establishment_geo_public(department_id, province_id, district_id)
    if not dept:
        prov = None
        dist = None
    elif not prov:
        dist = None
    return country, dept, prov, dist


def upsert_establishment(db: Session, tenant_id: UUID, body: EstablishmentWrite) -> m.InvEstablishment:
    country_id, department_id, province_id, district_id = _normalize_geo_ids(
        body.country_id,
        body.department_id,
        body.province_id,
        body.district_id,
    )
    body.country_id = country_id
    body.department_id = department_id
    body.province_id = province_id
    body.district_id = district_id
    geo.validate_establishment_geo_ids(
        db,
        country_id,
        department_id,
        province_id,
        district_id,
    )
    if body.id:
        row = db.get(m.InvEstablishment, body.id)
        if not row or row.tenant_id != tenant_id:
            raise ValueError("Establecimiento no encontrado")
        for f in (
            "description",
            "country_id",
            "department_id",
            "province_id",
            "district_id",
            "address",
            "email",
            "telephone",
            "code",
            "trade_address",
            "web_address",
            "aditional_information",
            "customer_id",
            "latitude",
            "longitude",
        ):
            setattr(row, f, getattr(body, f))
        _apply_establishment_photo(row, body)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    data = body.model_dump(exclude=_PHOTO_WRITE_EXCLUDE)
    row = m.InvEstablishment(tenant_id=tenant_id, **data)
    _apply_establishment_photo(row, body)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_establishments(db: Session, tenant_id: UUID, q: RecordQuery, allowed_cols: set[str]) -> tuple[list[dict], int]:
    col = q.column if q.column in allowed_cols else "code"
    stmt = select(m.InvEstablishment).where(m.InvEstablishment.tenant_id == tenant_id)
    pattern = _search_like(q)
    if pattern is not None:
        stmt = stmt.where(
            or_(
                m.InvEstablishment.code.ilike(pattern),
                m.InvEstablishment.description.ilike(pattern),
                m.InvEstablishment.address.ilike(pattern),
                m.InvEstablishment.email.ilike(pattern),
                m.InvEstablishment.telephone.ilike(pattern),
            )
        )
    elif q.value not in (None, ""):
        stmt = stmt.where(getattr(m.InvEstablishment, col).ilike(f"%{q.value}%"))
    order_col = q.column_ord or col
    if order_col not in allowed_cols | {"id", "created_at"}:
        order_col = "id"
    stmt = stmt.order_by(_ord_clause(m.InvEstablishment, order_col, q.ord_tipo))
    rows, total = _paged(db, stmt, q.page, q.per_page)
    return [establishment_row_public_dict(r) for r in rows], total


# --- Personas ---


def upsert_person(db: Session, tenant_id: UUID, body: PersonWrite) -> m.InvPerson:
    data = body.model_dump(exclude={"id"})
    if body.id:
        row = db.get(m.InvPerson, body.id)
        if not row or row.tenant_id != tenant_id:
            raise ValueError("Persona no encontrada")
        for k, v in data.items():
            setattr(row, k, v)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    row = m.InvPerson(tenant_id=tenant_id, **data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_persons(db: Session, tenant_id: UUID, q: RecordQuery, allowed_cols: set[str]) -> tuple[list[dict], int]:
    col = q.column if q.column in allowed_cols else "name"
    stmt = select(m.InvPerson).where(m.InvPerson.tenant_id == tenant_id)
    pattern = _search_like(q)
    if pattern is not None:
        extra = m.InvPerson.extra
        stmt = stmt.where(
            or_(
                m.InvPerson.name.ilike(pattern),
                m.InvPerson.number.ilike(pattern),
                m.InvPerson.email.ilike(pattern),
                m.InvPerson.telephone.ilike(pattern),
                m.InvPerson.enviroment_code.ilike(pattern),
                m.InvPerson.cc_code.ilike(pattern),
                m.InvPerson.type.ilike(pattern),
                extra["codigo_interno"].astext.ilike(pattern),
                extra["nombre"].astext.ilike(pattern),
                extra["apellido_paterno"].astext.ilike(pattern),
                extra["apellido_materno"].astext.ilike(pattern),
            )
        )
    elif q.value not in (None, ""):
        stmt = stmt.where(getattr(m.InvPerson, col).ilike(f"%{q.value}%"))
    order_col = q.column_ord or col
    if order_col not in allowed_cols | {"id", "created_at"}:
        order_col = "id"
    stmt = stmt.order_by(_ord_clause(m.InvPerson, order_col, q.ord_tipo))
    rows, total = _paged(db, stmt, q.page, q.per_page)
    if not rows:
        return [], total
    codes: set[str] = set()
    for r in rows:
        if r.cc_code and str(r.cc_code).strip():
            codes.add(str(r.cc_code).strip())
    cc_map: dict[str, str] = {}
    if codes:
        for cc in db.scalars(
            select(m.InvCostCenter).where(
                m.InvCostCenter.tenant_id == tenant_id,
                m.InvCostCenter.code.in_(sorted(codes)),
            )
        ):
            cc_map[cc.code] = (cc.description or "").strip() or cc.code
    out: list[dict[str, Any]] = []
    for r in rows:
        d = row_to_dict(r)
        ex_raw = d.get("extra")
        ex: dict[str, Any] = ex_raw if isinstance(ex_raw, dict) else {}
        codigo = str(ex.get("codigo_interno") or "").strip()
        ap_pat = str(ex.get("apellido_paterno") or "").strip()
        ap_mat = str(ex.get("apellido_materno") or "").strip()
        nombre = str(ex.get("nombre") or "").strip()
        if not (ap_pat or ap_mat or nombre):
            legacy = str(d.get("name") or "").strip()
            if legacy:
                nombre = legacy
        apellidos = " ".join(x for x in (ap_pat, ap_mat) if x).strip() or "—"
        nombres = nombre or "—"
        doc_t = str(d.get("identity_document_type_id") or "").strip()
        doc_n = str(d.get("number") or "").strip()
        documento = " ".join(x for x in (doc_t, doc_n) if x).strip() or "—"
        cc_c = str(d.get("cc_code") or "").strip()
        centro = cc_map.get(cc_c, cc_c) if cc_c else "—"
        movil = str(ex.get("movil") or "").strip()
        tel_raw = str(d.get("telephone") or "").strip()
        telefono = movil or tel_raw or "—"
        correo = str(d.get("email") or "").strip() or "—"
        d["codigo"] = codigo or "—"
        d["documento"] = documento
        d["apellidos"] = apellidos
        d["nombres"] = nombres
        d["telefono"] = telefono
        d["correo"] = correo
        d["centro_costo"] = centro
        out.append(d)
    return out, total


# --- Centro de costo (CentroCostoController) ---


def _cost_center_duplicate_code(
    db: Session,
    tenant_id: UUID,
    code: str,
    exclude_id: int | None = None,
) -> bool:
    stmt = select(m.InvCostCenter.id).where(
        m.InvCostCenter.tenant_id == tenant_id,
        m.InvCostCenter.code == code,
    )
    if exclude_id is not None:
        stmt = stmt.where(m.InvCostCenter.id != exclude_id)
    return db.scalar(stmt) is not None


def _raise_duplicate_cost_center_code(code: str) -> None:
    raise ValueError(
        f"Ya existe un centro de costo con el código «{code}». "
        "Use otro código interno o edite el registro existente."
    )


def upsert_cost_center(db: Session, tenant_id: UUID, body: CostCenterWrite) -> m.InvCostCenter:
    code = (body.code or "").strip()
    if not code:
        raise ValueError("El código interno es obligatorio")

    if body.personal_id is not None and body.personal_id > 0:
        p = db.get(m.InvPerson, body.personal_id)
        if not p or p.tenant_id != tenant_id:
            raise ValueError("Persona encargado no válida o no encontrada")
    if body.principal_center_id is not None and body.principal_center_id > 0:
        parent = db.get(m.InvCostCenter, body.principal_center_id)
        if not parent or parent.tenant_id != tenant_id:
            raise ValueError("Centro de costo principal no válido o no encontrado")
        if body.id and parent.id == body.id:
            raise ValueError("El centro de costo principal no puede ser el mismo registro")

    if _cost_center_duplicate_code(db, tenant_id, code, body.id):
        _raise_duplicate_cost_center_code(code)

    data = body.model_dump(exclude={"id"})
    data["code"] = code
    desc = str(data.get("description") or "").strip()
    data["description"] = desc[:70]
    try:
        if body.id:
            row = db.get(m.InvCostCenter, body.id)
            if not row or row.tenant_id != tenant_id:
                raise ValueError("Centro de costo no encontrado")
            for k, v in data.items():
                setattr(row, k, v)
            db.add(row)
            db.commit()
            db.refresh(row)
            return row
        row = m.InvCostCenter(tenant_id=tenant_id, **data)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    except IntegrityError as e:
        db.rollback()
        orig = str(e.orig) if e.orig else str(e)
        if "uq_inv_cost_center_tenant_code" in orig:
            _raise_duplicate_cost_center_code(code)
        raise ValueError("No se pudo guardar el centro de costo.") from e


def delete_cost_center(db: Session, tenant_id: UUID, cc_id: int) -> tuple[bool, str]:
    row = db.get(m.InvCostCenter, cc_id)
    if not row or row.tenant_id != tenant_id:
        return False, "Centro de costo no encontrado"
    dep = db.scalar(
        select(m.InvCostCenter).where(
            m.InvCostCenter.tenant_id == tenant_id,
            m.InvCostCenter.principal_center_id == cc_id,
        )
    )
    if dep:
        return False, "No se puede eliminar porque tiene Centros de Costos dependientes."
    card = db.scalar(select(m.InvCard).where(m.InvCard.tenant_id == tenant_id, m.InvCard.id_ccosto == cc_id))
    if card:
        return False, "No se puede eliminar porque tiene Hojas de captura asignadas."
    db.delete(row)
    db.commit()
    return True, "Centro de Costo eliminado con éxito"


def list_cost_centers(db: Session, tenant_id: UUID, q: RecordQuery, allowed_cols: set[str]) -> tuple[list[dict], int]:
    col = q.column if q.column in allowed_cols else "code"
    stmt = select(m.InvCostCenter).where(m.InvCostCenter.tenant_id == tenant_id)
    pattern = _search_like(q)
    if pattern is not None:
        enc = m.InvPerson
        stmt = (
            stmt.outerjoin(enc, (enc.id == m.InvCostCenter.personal_id) & (enc.tenant_id == m.InvCostCenter.tenant_id))
            .where(
                or_(
                    m.InvCostCenter.code.ilike(pattern),
                    m.InvCostCenter.description.ilike(pattern),
                    enc.number.ilike(pattern),
                    enc.name.ilike(pattern),
                )
            )
            .distinct()
        )
    elif q.value not in (None, ""):
        stmt = stmt.where(getattr(m.InvCostCenter, col).ilike(f"%{q.value}%"))
    order_col = q.column_ord or col
    if order_col not in allowed_cols | {"id", "created_at"}:
        order_col = "code"
    stmt = stmt.order_by(_ord_clause(m.InvCostCenter, order_col, q.ord_tipo))
    rows, total = _paged(db, stmt, q.page, q.per_page)
    if not rows:
        return [], total
    p_ids = {r.personal_id for r in rows if r.personal_id}
    persons_map: dict[int, m.InvPerson] = {}
    if p_ids:
        for p in db.scalars(
            select(m.InvPerson).where(m.InvPerson.tenant_id == tenant_id, m.InvPerson.id.in_(p_ids))
        ):
            persons_map[p.id] = p
    out: list[dict[str, Any]] = []
    for r in rows:
        d = row_to_dict(r)
        enc = "—"
        if r.personal_id and r.personal_id in persons_map:
            p = persons_map[r.personal_id]
            num = (p.number or "").strip()
            nm = (p.name or "").strip()
            parts = [x for x in (num, nm) if x]
            enc = " · ".join(parts) if parts else "—"
        d["encargado"] = enc
        out.append(d)
    return out, total


# --- Ambientes (AmbientesController) ---


def upsert_environment(db: Session, tenant_id: UUID, body: EnvironmentWrite) -> m.InvEnvironment:
    data = body.model_dump(exclude={"id"})
    if body.id:
        row = db.get(m.InvEnvironment, body.id)
        if not row or row.tenant_id != tenant_id:
            raise ValueError("Ambiente no encontrado")
        for k, v in data.items():
            setattr(row, k, v)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    row = m.InvEnvironment(tenant_id=tenant_id, **data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_environment(db: Session, tenant_id: UUID, env_id: int) -> tuple[bool, str]:
    row = db.get(m.InvEnvironment, env_id)
    if not row or row.tenant_id != tenant_id:
        return False, "Ambiente no encontrado"
    persons = db.scalar(
        select(m.InvPerson).where(m.InvPerson.tenant_id == tenant_id, m.InvPerson.enviroment_code == row.code)
    )
    if persons:
        return False, "No se puede eliminar porque tiene Personal asignado."
    cards = db.scalar(select(m.InvCard).where(m.InvCard.tenant_id == tenant_id, m.InvCard.id_ambiente == env_id))
    if cards:
        return False, "No se puede eliminar porque tiene Hojas de Captura asignadas."
    db.delete(row)
    db.commit()
    return True, "Ambiente eliminado con éxito"


def list_environments(
    db: Session, tenant_id: UUID, q: RecordQuery, allowed_cols: set[str]
) -> tuple[list[dict], int]:
    """`records` con filtro por relación `local` como en AmbientesController."""
    order_col = q.column_ord or "code"
    if order_col not in allowed_cols | {"id", "created_at"}:
        order_col = "code"
    stmt = select(m.InvEnvironment).where(m.InvEnvironment.tenant_id == tenant_id)
    if q.establishment_id is not None:
        stmt = stmt.where(m.InvEnvironment.establishment_id == q.establishment_id)

    pattern = _search_like(q)
    if pattern is not None:
        est = m.InvEstablishment
        stmt = (
            stmt.outerjoin(
                est,
                (est.id == m.InvEnvironment.establishment_id) & (est.tenant_id == m.InvEnvironment.tenant_id),
            )
            .where(
                or_(
                    m.InvEnvironment.code.ilike(pattern),
                    m.InvEnvironment.description.ilike(pattern),
                    m.InvEnvironment.floor.ilike(pattern),
                    m.InvEnvironment.telephone.ilike(pattern),
                    est.code.ilike(pattern),
                    est.description.ilike(pattern),
                )
            )
            .distinct()
        )
    elif q.column == "local" and q.value not in (None, ""):
        sub = select(m.InvEstablishment.id).where(
            m.InvEstablishment.tenant_id == tenant_id,
            m.InvEstablishment.description.ilike(f"%{q.value}%"),
        )
        stmt = stmt.where(m.InvEnvironment.establishment_id.in_(sub))
    elif q.value not in (None, ""):
        col = q.column if q.column in allowed_cols else "code"
        stmt = stmt.where(getattr(m.InvEnvironment, col).ilike(f"%{q.value}%"))

    stmt = stmt.order_by(_ord_clause(m.InvEnvironment, order_col, q.ord_tipo))
    rows, total = _paged(db, stmt, q.page, q.per_page)
    return [row_to_dict(r) for r in rows], total


# --- Cards (CardsController / HojaCapturaController) ---


def _parse_sheet_num(raw: int | str) -> int:
    return parse_inventory_number(raw, field="Número de hoja", allow_empty=True)


def user_inventory_conf(user: User | None) -> UserInventoryConf:
    if not user:
        return UserInventoryConf()
    return UserInventoryConf(
        num_ini=user.num_ini,
        num_fin=user.num_fin,
        num_act=user.num_act,
        eti_ini=user.eti_ini,
        eti_fin=user.eti_fin,
        eti_act=user.eti_act,
    )


def _validate_hoj_num_range(user: User | None, hoj_num: int) -> None:
    if not user or user.num_ini is None or user.num_fin is None:
        return
    if not (int(user.num_ini) <= hoj_num <= int(user.num_fin)):
        raise ValueError("Número de hoja fuera de rango")


def _hoj_num_taken(db: Session, tenant_id: UUID, hoj_num: int, exclude_id: int | None = None) -> bool:
    stmt = select(m.InvCard.id).where(m.InvCard.tenant_id == tenant_id, m.InvCard.hoj_num == hoj_num)
    if exclude_id:
        stmt = stmt.where(m.InvCard.id != exclude_id)
    return db.scalar(stmt) is not None


def update_user_inventory_num(db: Session, tenant_id: UUID, user_id: UUID, body: InventoryNumWrite) -> User:
    user = db.get(User, user_id)
    if not user or user.tenant_id != tenant_id or user.is_deleted:
        raise ValueError("Usuario no encontrado")
    if body.num_act is not None:
        user.num_act = body.num_act
    if body.eti_act is not None:
        user.eti_act = body.eti_act
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def hoja_captura_tables(db: Session, tenant_id: UUID, user_id: UUID) -> dict[str, Any]:
    user = db.get(User, user_id)
    persons, _ = list_persons(db, tenant_id, RecordQuery(page=1, per_page=2000, column="number"), {"number", "name"})
    envs, _ = list_environments(db, tenant_id, RecordQuery(page=1, per_page=2000, column="code"), {"code", "description"})
    ests, _ = list_establishments(
        db, tenant_id, RecordQuery(page=1, per_page=2000, column="code"), {"code", "description"}
    )
    ccs, _ = list_cost_centers(db, tenant_id, RecordQuery(page=1, per_page=2000, column="code"), {"code", "description"})
    iam_users = db.scalars(
        select(User).where(User.tenant_id == tenant_id, User.is_deleted.is_(False)).order_by(User.full_name)
    ).all()
    users_out = [
        {"id": str(u.id), "full_name": u.full_name, "email": u.email, **user_inventory_conf(u).model_dump()}
        for u in iam_users
    ]
    return {
        "persons": persons,
        "environments": envs,
        "establishments": ests,
        "cost_centers": ccs,
        "users": users_out,
        "user_conf": user_inventory_conf(user).model_dump(),
    }


def item_card_tables(db: Session, tenant_id: UUID, user_id: UUID) -> dict[str, Any]:
    from app.core.config import get_settings

    user = db.get(User, user_id)
    sbn, _ = list_list_sbn(db, tenant_id, RecordQuery(page=1, per_page=2000, column="code"), {"code", "cat_des"})
    host = (get_settings().public_api_base_url or "").rstrip("/") or None
    return {"list_sbn": sbn, "user_conf": user_inventory_conf(user).model_dump(), "host": host}


def save_hoja_captura_item_photo(
    tenant_id: UUID, inv_num: int | str, slot: int, content: bytes, original_name: str
) -> str:
    from app.core.item_photo_storage import upload_item_photo

    _ = original_name
    inv_label = format_inv_num(inv_num) if isinstance(inv_num, int) else str(inv_num)
    return upload_item_photo(tenant_id=tenant_id, inv_num=inv_label, slot=slot, content=content)


def _find_margesi_by_tipo(db: Session, tenant_id: UUID, valor: str, tipo: str) -> m.InvMargesiItem | None:
    from app.modules.inventory.margesi_mapper import coerce_column_value

    v = valor.strip()
    t = tipo.strip().upper()
    if not v:
        return None
    base = select(m.InvMargesiItem).where(m.InvMargesiItem.tenant_id == tenant_id)
    if t == "M":
        stmt = base.where(m.InvMargesiItem.mar_num == v)
    elif t == "S":
        stmt = base.where(m.InvMargesiItem.mar_cpat == v)
    elif t == "A":
        inv1 = coerce_column_value("inv_num_1", v)
        if inv1 is None:
            return None
        stmt = base.where(m.InvMargesiItem.inv_num_1 == inv1)
    elif t == "R":
        inv2 = coerce_column_value("inv_num_2", v)
        if inv2 is None:
            return None
        stmt = base.where(m.InvMargesiItem.inv_num_2 == inv2)
    elif t in ("SE", "I"):
        stmt = base.where(m.InvMargesiItem.inv_num == v)
    else:
        return None
    return db.scalar(stmt.limit(1))


def _margesi_to_lookup_item(row: m.InvMargesiItem) -> dict[str, Any]:
    from app.modules.inventory.margesi_mapper import margesi_row_to_api

    d = margesi_row_to_api(row)
    if not d.get("mar_ccat"):
        d["mar_ccat"] = d.get("mar_cpat")
    return d


def _card_summary_for_inv_hoj(db: Session, tenant_id: UUID, inv_hoj: str | None) -> dict[str, Any] | None:
    hoj = (inv_hoj or "").strip()
    if not hoj:
        return None
    hoj_n = try_parse_inventory_number(hoj)
    if hoj_n is None:
        return {"hoj_num": hoj, "local": None, "ambiente": None}
    card = db.scalar(select(m.InvCard).where(m.InvCard.tenant_id == tenant_id, m.InvCard.hoj_num == hoj_n))
    if not card:
        return {"hoj_num": hoj, "local": None, "ambiente": None}
    ambiente = db.get(m.InvEnvironment, card.id_ambiente) if card.id_ambiente else None
    local_desc = None
    if ambiente and ambiente.establishment_id:
        est = db.get(m.InvEstablishment, ambiente.establishment_id)
        if est:
            local_desc = f"{est.code} - {est.description or ''}".strip(" -")
    amb_desc = None
    if ambiente:
        amb_desc = f"{ambiente.code} - {ambiente.description or ''}".strip(" -")
    return {"hoj_num": hoj, "local": local_desc, "ambiente": amb_desc}


def record_margesi_cod(
    db: Session, tenant_id: UUID, valor: str, tipo: str, user_id: UUID
) -> dict[str, Any]:
    """Equivalente a `MargesiController@recordCod`."""
    row = _find_margesi_by_tipo(db, tenant_id, valor, tipo)
    if not row:
        return {"success": False, "message": "Bien no se encuentra", "esta_conciliado": False}
    if (row.inv_sit or "").strip().upper() == "N":
        return {"success": False, "message": "Bien no conciliable", "esta_conciliado": False}

    user = db.get(User, user_id)
    eti = user.eti_act if user and user.eti_act is not None else None
    inv_sugerido = str(eti) if eti is not None else None

    if row.inv_num and str(row.inv_num).strip():
        inv_hoj = row.inv_hoj
        card_label = inv_hoj
        if inv_hoj:
            hoj_n = try_parse_inventory_number(inv_hoj)
            card = None
            if hoj_n is not None:
                card = db.scalar(
                    select(m.InvCard).where(m.InvCard.tenant_id == tenant_id, m.InvCard.hoj_num == hoj_n)
                )
            if card:
                card_label = f"{inv_hoj} (ID {card.id})"
        return {
            "success": True,
            "message": f"El bien ya está inventariado en la hoja {card_label or inv_hoj or '—'}",
            "esta_conciliado": True,
            "inv_hoj": inv_hoj,
            "id_margesi": row.id,
            "inv_num_sugerido": inv_sugerido,
            "item": _margesi_to_lookup_item(row),
            "card_info": _card_summary_for_inv_hoj(db, tenant_id, inv_hoj),
        }

    return {
        "success": True,
        "message": "Bien disponible para inventariar",
        "esta_conciliado": False,
        "inv_hoj": None,
        "id_margesi": row.id,
        "inv_num_sugerido": inv_sugerido,
        "item": _margesi_to_lookup_item(row),
    }


def upsert_card(
    db: Session,
    tenant_id: UUID,
    body: CardWrite,
    digitador_id: UUID,
    *,
    hoja_captura_mode: bool = True,
) -> m.InvCard:
    if not body.hoj_fec:
        raise ValueError("La fecha de registro es obligatoria")
    if not body.id_ambiente or not body.id_ccosto:
        raise ValueError("Ambiente y centro de costo son obligatorios")
    if body.id_inventariador is None:
        raise ValueError("El inventariador es obligatorio")

    effective_digitador = body.id_digitador or digitador_id
    if effective_digitador is None:
        raise ValueError("El digitador es obligatorio")

    user = db.get(User, effective_digitador)
    hoj_n = _parse_sheet_num(body.hoj_num)

    data = body.model_dump(exclude={"id"})
    data["id_digitador"] = effective_digitador
    data["hoj_num"] = hoj_n

    if body.id:
        row = db.get(m.InvCard, body.id)
        if not row or row.tenant_id != tenant_id:
            raise ValueError("Hoja no encontrada")
        if _hoj_num_taken(db, tenant_id, hoj_n, exclude_id=body.id):
            raise ValueError("Número de hoja ya registrado")
        _validate_hoj_num_range(user, hoj_n)
        for k, v in data.items():
            setattr(row, k, v)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    if _hoj_num_taken(db, tenant_id, hoj_n):
        raise ValueError("Número de hoja ya registrado")
    _validate_hoj_num_range(user, hoj_n)

    row = m.InvCard(tenant_id=tenant_id, **data)
    db.add(row)
    db.flush()

    if user:
        if hoja_captura_mode:
            user.num_act = hoj_n + 1
        else:
            user.num_act = int(user.num_act or hoj_n) + 1
        db.add(user)

    db.commit()
    db.refresh(row)
    return row


def list_cards(db: Session, tenant_id: UUID, q: RecordQuery, allowed_cols: set[str]) -> tuple[list[dict], int]:
    col = q.column if q.column in allowed_cols else "hoj_num"
    stmt = select(m.InvCard).where(m.InvCard.tenant_id == tenant_id)
    if q.flag_firma is not None:
        stmt = stmt.where(m.InvCard.flag_firma.is_(q.flag_firma))
    pattern = _search_like(q)
    if pattern is not None:
        env = m.InvEnvironment
        cc = m.InvCostCenter
        stmt = (
            stmt.outerjoin(env, (env.id == m.InvCard.id_ambiente) & (env.tenant_id == m.InvCard.tenant_id))
            .outerjoin(cc, (cc.id == m.InvCard.id_ccosto) & (cc.tenant_id == m.InvCard.tenant_id))
            .where(
                or_(
                    numeric_column_ilike(m.InvCard.hoj_num, pattern),
                    m.InvCard.nota_interna.ilike(pattern),
                    m.InvCard.nota_ficha.ilike(pattern),
                    env.code.ilike(pattern),
                    env.description.ilike(pattern),
                    cc.code.ilike(pattern),
                    cc.description.ilike(pattern),
                )
            )
            .distinct()
        )
    elif q.value not in (None, ""):
        if col in _CARD_INT_FILTER_COLS:
            stmt = stmt.where(_where_column_ilike(m.InvCard, col, q.value, numeric_cols=_CARD_INT_FILTER_COLS))
        else:
            stmt = stmt.where(getattr(m.InvCard, col).ilike(f"%{q.value}%"))
    order_col = q.column_ord or "hoj_num"
    if order_col not in allowed_cols | {"id", "created_at"}:
        order_col = "hoj_num"
    stmt = stmt.order_by(_ord_clause(m.InvCard, order_col, q.ord_tipo))
    rows, total = _paged(db, stmt, q.page, q.per_page)
    if not rows:
        return [], total
    card_ids = [r.id for r in rows]
    eids = {r.id_ambiente for r in rows}
    ccids = {r.id_ccosto for r in rows}
    puids = {r.id_usuario for r in rows if r.id_usuario}

    env_map: dict[int, m.InvEnvironment] = {}
    if eids:
        for e in db.scalars(
            select(m.InvEnvironment).where(m.InvEnvironment.tenant_id == tenant_id, m.InvEnvironment.id.in_(eids))
        ):
            env_map[e.id] = e
    est_ids = {e.establishment_id for e in env_map.values()}
    est_map: dict[int, m.InvEstablishment] = {}
    if est_ids:
        for es in db.scalars(
            select(m.InvEstablishment).where(
                m.InvEstablishment.tenant_id == tenant_id, m.InvEstablishment.id.in_(est_ids)
            )
        ):
            est_map[es.id] = es

    cc_map: dict[int, m.InvCostCenter] = {}
    if ccids:
        for cc in db.scalars(
            select(m.InvCostCenter).where(m.InvCostCenter.tenant_id == tenant_id, m.InvCostCenter.id.in_(ccids))
        ):
            cc_map[cc.id] = cc

    pers_map: dict[int, m.InvPerson] = {}
    if puids:
        for p in db.scalars(
            select(m.InvPerson).where(m.InvPerson.tenant_id == tenant_id, m.InvPerson.id.in_(puids))
        ):
            pers_map[p.id] = p

    counts: dict[int, int] = {}
    if card_ids:
        stmt_cnt = (
            select(m.InvItemCard.id_card, func.count())
            .where(m.InvItemCard.tenant_id == tenant_id, m.InvItemCard.id_card.in_(card_ids))
            .group_by(m.InvItemCard.id_card)
        )
        for cid, n in db.execute(stmt_cnt).all():
            counts[int(cid)] = int(n)

    out: list[dict[str, Any]] = []
    for r in rows:
        d = inventory_row_dict(r)
        env = env_map.get(r.id_ambiente)
        if env:
            est = est_map.get(env.establishment_id)
            loc = ""
            if est:
                loc = " · ".join(x for x in ((est.code or "").strip(), (est.description or "").strip()) if x)
            amb = " · ".join(x for x in ((env.code or "").strip(), (env.description or "").strip()) if x)
            d["ambiente"] = " / ".join(x for x in (loc, amb) if x) or "—"
        else:
            d["ambiente"] = "—"
        cc = cc_map.get(r.id_ccosto)
        if cc:
            d["centro_costo"] = " · ".join(
                x for x in ((cc.code or "").strip(), (cc.description or "").strip()) if x
            ) or "—"
        else:
            d["centro_costo"] = "—"
        p = pers_map.get(r.id_usuario) if r.id_usuario else None
        if p:
            parts = ((p.number or "").strip(), (p.name or "").strip())
            d["usuario"] = " · ".join(x for x in parts if x) or "—"
        else:
            d["usuario"] = "—"
        d["items"] = counts.get(r.id, 0)
        d["firma"] = "Sí" if r.flag_firma else "No"
        out.append(d)
    return out, total


def close_card(db: Session, tenant_id: UUID, card_id: int) -> tuple[bool, str]:
    """Cierra hoja (`closedCard`): marca estado y nombres PDF (sin generar PDF binario)."""
    row = db.get(m.InvCard, card_id)
    if not row or row.tenant_id != tenant_id:
        return False, "Hoja no encontrada"
    if not row.flag_firma:
        return False, "Debe marcar el flag de firma antes de cerrar la hoja"
    num = int(row.hoj_num)
    row.pdf = f"HC-{format_hoj_num(num)}.pdf"
    row.pdf2 = f"FA-{format_hoj_num(num)}.pdf"
    row.state = 2
    db.add(row)
    db.commit()
    return True, "Hoja de captura cerrada."


def open_card(db: Session, tenant_id: UUID, card_id: int) -> tuple[bool, str]:
    row = db.get(m.InvCard, card_id)
    if not row or row.tenant_id != tenant_id:
        return False, "Hoja no encontrada"
    row.state = 1
    db.add(row)
    db.commit()
    return True, "Hoja de captura abierta."


def build_hoja_captura_ficha_pdf(db: Session, tenant_id: UUID, card_id: int) -> tuple[bytes, str]:
    from app.modules.inventory.hoja_captura_pdf import generate_ficha_pdf

    return generate_ficha_pdf(db, tenant_id, card_id)


def _inv_num_in_use(db: Session, tenant_id: UUID, inv_num: int, exclude_id: int | None = None) -> bool:
    stmt = select(m.InvItemCard.id).where(
        m.InvItemCard.tenant_id == tenant_id,
        m.InvItemCard.inv_num == inv_num,
    )
    if exclude_id:
        stmt = stmt.where(m.InvItemCard.id != exclude_id)
    return db.scalar(stmt) is not None


def _validate_card_item_fields(body: CardItemWrite) -> str | None:
    if body.inv_num is None:
        return "Número de inventario obligatorio"
    required = {
        "mar_col": body.mar_col,
        "mar_mar": body.mar_mar,
        "mar_mod": body.mar_mod,
        "mar_ser": body.mar_ser,
        "mar_med": body.mar_med,
    }
    labels = {
        "mar_col": "Color",
        "mar_mar": "Marca",
        "mar_mod": "Modelo",
        "mar_ser": "Serie",
        "mar_med": "Medidas",
    }
    if not body.id:
        required["mar_des"] = body.mar_des
        labels["mar_des"] = "Descripción"
    for key, val in required.items():
        if not (val and str(val).strip()):
            return f"{labels[key]} es obligatorio"
    return None


def _bump_eti_act(user: User | None, inv_num: int | None) -> None:
    if not user or inv_num is None:
        return
    user.eti_act = int(inv_num) + 1


def _log_item_registration(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    itemcard_id: int,
    card_id: int,
    inv_num: int | str | None = None,
) -> None:
    """Append-only: un INSERT en la misma transacción, sin consultas extra."""
    db.add(
        m.InvItemRegistrationLog(
            tenant_id=tenant_id,
            user_id=user_id,
            itemcard_id=itemcard_id,
            card_id=card_id,
            inv_num=format_inv_num(inv_num) if isinstance(inv_num, int) else inv_num,
        )
    )


def _log_item_audit(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID | None,
    action: str,
    itemcard_id: int | None,
    card_id: int,
    inv_num: int | str | None = None,
    mar_des: str | None = None,
) -> None:
    """Append-only: auditoría de bienes sin consultas extra."""
    db.add(
        m.InvItemAuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action,
            itemcard_id=itemcard_id,
            card_id=card_id,
            inv_num=format_inv_num(inv_num) if isinstance(inv_num, int) else inv_num,
            mar_des=mar_des,
        )
    )


def _normalize_hoj_num(value: int | str | None) -> str:
    if value is None:
        return format_hoj_num(0)
    if isinstance(value, int):
        return format_hoj_num(value)
    return format_hoj_num(parse_inventory_number(value, field="Número de hoja", allow_empty=True))


def _margesi_internal_code(row: m.InvMargesiItem) -> str | None:
    code = str(row.mar_num or "").strip()
    if code:
        return code
    ex = row.extra if isinstance(row.extra, dict) else {}
    alt = str(ex.get("codigo_interno") or "").strip()
    return alt or None


def _link_item_to_margesi(
    card: m.InvCard,
    ict: m.InvItemCard,
    marg: m.InvMargesiItem,
    *,
    mar_cpat: str | None = None,
) -> None:
    """Marca conciliación inventario ↔ margesi (sin modificar ``mar_des`` del catálogo)."""
    hoj = _normalize_hoj_num(card.hoj_num)
    inv = ict.inv_num
    if inv is not None:
        marg.inv_num = format_inv_num(inv)
    marg.inv_hoj = hoj
    marg.inv_sit = "C"
    marg.inv_con = "1"

    ict.id_margesi = int(marg.id)
    ict.inv_sit = "C"
    ict.inv_con = "1"

    internal = _margesi_internal_code(marg)
    if internal:
        ict.mar_num = internal

    cpat = (mar_cpat or ict.mar_cpat or marg.mar_cpat or "").strip()
    if cpat:
        ict.mar_cpat = cpat

    if marg.mar_des:
        ict.mar_des = marg.mar_des


def store_card_item(
    db: Session,
    tenant_id: UUID,
    card_id: int,
    body: CardItemWrite,
    *,
    operator_id: UUID | None = None,
) -> tuple[bool, str]:
    """Lógica de `CardsController::storeItem` (crear / actualizar ítem y sincronizar `margesi`)."""
    card = db.get(m.InvCard, card_id)
    if not card or card.tenant_id != tenant_id:
        return False, "Hoja no encontrada"
    if card.state == 2 and not body.id:
        return False, "La hoja está cerrada; no se pueden agregar bienes"

    err = _validate_card_item_fields(body)
    if err:
        return False, err

    inv_num = body.inv_num
    if inv_num is None:
        return False, "Número de inventario obligatorio"
    if _inv_num_in_use(db, tenant_id, inv_num, exclude_id=body.id):
        return False, "Número de inventario ya registrado"

    operator = db.get(User, operator_id) if operator_id else None

    extra_keys = {
        "mar_ano",
        "mar_ccat",
        "mar_col",
        "mar_esp",
        "mar_est",
        "mar_eti",
        "mar_flag",
        "mar_foto",
        "mar_foto2",
        "mar_foto3",
        "mar_mar",
        "mar_med",
        "mar_mod",
        "mar_ncha",
        "mar_nmot",
        "mar_npla",
        "mar_npri",
        "mar_obs",
        "mar_seg",
        "mar_ser",
        "mar_tip",
        "mar_uso",
    }
    dump = body.model_dump()
    patch_extra: dict[str, Any] = {k: dump[k] for k in extra_keys if dump.get(k) is not None}

    if body.id:
        ict = db.get(m.InvItemCard, body.id)
        if not ict or ict.tenant_id != tenant_id or ict.id_card != card_id:
            return False, "Ítem no encontrado en esta hoja"
        ict.inv_num = body.inv_num
        ict.inv_num_1 = body.inv_num_1
        ict.inv_num_2 = body.inv_num_2
        was_sobrante = not ict.id_margesi and str(ict.inv_sit or "").strip().upper() == "S"
        if body.mar_num is not None and not ict.id_margesi:
            ict.mar_num = body.mar_num
        if not ict.id_margesi:
            if was_sobrante or body.no_conciliar:
                if body.mar_cpat is not None:
                    ict.mar_cpat = (body.mar_cpat or "").strip() or None
                if body.mar_des is not None:
                    ict.mar_des = (body.mar_des or "").strip() or None
            elif body.mar_cpat is not None:
                base = body.mar_cpat if body.mar_cpat is not None else ict.mar_cpat
                base = base or ""
                ict.mar_cpat = f"{base}{body.mar_cpat_num or ''}"
                if body.mar_des is not None:
                    ict.mar_des = (body.mar_des or "").strip() or None
        ict.extra = {**(ict.extra or {}), **patch_extra}
        if ict.id_margesi:
            marg = db.get(m.InvMargesiItem, ict.id_margesi)
            if marg and marg.tenant_id == tenant_id:
                _link_item_to_margesi(card, ict, marg)
                db.add(marg)
        elif body.id_margesi and not body.no_conciliar:
            marg = db.get(m.InvMargesiItem, body.id_margesi)
            if marg and marg.tenant_id == tenant_id:
                mar_cpat_base = body.mar_cpat or marg.mar_cpat or ""
                _link_item_to_margesi(card, ict, marg, mar_cpat=mar_cpat_base)
                db.add(marg)
        elif body.no_conciliar or was_sobrante:
            ict.inv_sit = "S"
            ict.inv_con = None
            ict.id_margesi = None
        db.add(ict)
        db.add(card)
        if operator:
            _bump_eti_act(operator, inv_num)
            db.add(operator)
        if operator_id:
            _log_item_audit(
                db,
                tenant_id=tenant_id,
                user_id=operator_id,
                action="update",
                itemcard_id=int(ict.id),
                card_id=card_id,
                inv_num=inv_num,
                mar_des=ict.mar_des,
            )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return False, "Número de inventario ya registrado"
        return True, "Item modificado"

    mar_cpat_base = (body.mar_cpat or "").strip()
    id_margesi = body.id_margesi
    if body.no_conciliar:
        id_margesi = None

    marg_row: m.InvMargesiItem | None = None
    if id_margesi:
        marg_row = db.get(m.InvMargesiItem, id_margesi)
        if marg_row is None or marg_row.tenant_id != tenant_id:
            return False, "Registro Margesi no encontrado"
        if not mar_cpat_base and marg_row.mar_cpat:
            mar_cpat_base = str(marg_row.mar_cpat).strip()

    if body.no_conciliar:
        inv_sit = "S"
        inv_con = None
    else:
        inv_sit = "C"
        inv_con = "1" if id_margesi else None

    initial_cpat = body.mar_cpat or ""
    item_des = body.mar_des
    if id_margesi and marg_row is not None:
        initial_cpat = mar_cpat_base
        if marg_row.mar_des:
            item_des = marg_row.mar_des

    ict = m.InvItemCard(
        tenant_id=tenant_id,
        id_card=card_id,
        inv_num=body.inv_num,
        mar_num=body.mar_num,
        mar_des=item_des,
        mar_cpat=initial_cpat or None,
        inv_sit=inv_sit,
        inv_con=inv_con,
        inv_num_1=body.inv_num_1,
        inv_num_2=body.inv_num_2,
        id_margesi=id_margesi,
        extra=patch_extra or None,
    )
    db.add(ict)
    db.flush()

    if operator_id:
        _log_item_registration(
            db,
            tenant_id=tenant_id,
            user_id=operator_id,
            itemcard_id=int(ict.id),
            card_id=card_id,
            inv_num=inv_num or None,
        )
        _log_item_audit(
            db,
            tenant_id=tenant_id,
            user_id=operator_id,
            action="create",
            itemcard_id=int(ict.id),
            card_id=card_id,
            inv_num=inv_num or None,
            mar_des=item_des,
        )

    if id_margesi and marg_row is not None:
        _link_item_to_margesi(card, ict, marg_row, mar_cpat=mar_cpat_base)
        db.add(marg_row)

    card.hoj_can_tot = int(card.hoj_can_tot or 0) + 1
    db.add(card)
    db.add(ict)
    if operator:
        _bump_eti_act(operator, inv_num)
        db.add(operator)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return False, "Número de inventario ya registrado"
    return True, "Item agregado"


def edit_card_item(
    db: Session, tenant_id: UUID, body: CardItemWrite, *, operator_id: UUID | None = None
) -> tuple[bool, str]:
    """Edición por ID de ítem (`hoja-captura/edit/item`)."""
    if not body.id:
        return False, "ID de ítem requerido"
    ict = db.get(m.InvItemCard, body.id)
    if not ict or ict.tenant_id != tenant_id:
        return False, "Ítem no encontrado"
    return store_card_item(db, tenant_id, int(ict.id_card), body, operator_id=operator_id)


def recount_card_items(db: Session, tenant_id: UUID) -> bool:
    """`contarBienes`: recalcula `hoj_can_tot` desde `itemcards`."""
    cards = db.scalars(select(m.InvCard).where(m.InvCard.tenant_id == tenant_id)).all()
    for c in cards:
        n = db.scalar(
            select(func.count()).select_from(m.InvItemCard).where(m.InvItemCard.id_card == c.id),
        )
        c.hoj_can_tot = int(n or 0)
        db.add(c)
    db.commit()
    return True


# --- Bienes / ItemTarjeta (BienesController) ---


def list_item_cards(db: Session, tenant_id: UUID, q: RecordQuery, allowed_cols: set[str]) -> tuple[list[dict], int]:
    order_col = q.column_ord or "id"
    if order_col not in allowed_cols | {"id", "created_at"}:
        order_col = "id"
    stmt = select(m.InvItemCard).where(m.InvItemCard.tenant_id == tenant_id)

    if q.inv_sit_filter in ("C", "S"):
        stmt = stmt.where(m.InvItemCard.inv_sit == q.inv_sit_filter)

    if q.column == "num_card" and q.value not in (None, ""):
        hoj_n = try_parse_inventory_number(q.value)
        card = None
        if hoj_n is not None:
            card = db.scalar(select(m.InvCard).where(m.InvCard.tenant_id == tenant_id, m.InvCard.hoj_num == hoj_n))
        if card:
            stmt = stmt.where(m.InvItemCard.id_card == card.id)
        else:
            stmt = stmt.where(m.InvItemCard.id == -1)
    elif q.column == "id_card" and q.value not in (None, ""):
        try:
            cid = int(q.value)
        except ValueError:
            cid = -1
        stmt = stmt.where(m.InvItemCard.id_card == cid)
    elif q.value not in (None, ""):
        col = q.column if q.column in allowed_cols else "inv_num"
        if col in _ITEMCARD_INT_FILTER_COLS:
            stmt = stmt.where(_where_column_ilike(m.InvItemCard, col, q.value, numeric_cols=_ITEMCARD_INT_FILTER_COLS))
        else:
            stmt = stmt.where(getattr(m.InvItemCard, col).ilike(f"%{q.value}%"))

    stmt = stmt.order_by(_ord_clause(m.InvItemCard, order_col, q.ord_tipo))
    rows, total = _paged(db, stmt, q.page, q.per_page)
    if not rows:
        return [], total
    card_ids = {int(r.id_card) for r in rows}
    card_map: dict[int, str | None] = {}
    if card_ids:
        for c in db.scalars(select(m.InvCard).where(m.InvCard.tenant_id == tenant_id, m.InvCard.id.in_(card_ids))):
            card_map[int(c.id)] = c.hoj_num
    out: list[dict[str, Any]] = []
    for r in rows:
        d = inventory_row_dict(r)
        d["num_card"] = card_map.get(int(r.id_card))
        out.append(d)
    return out, total


def translate_item_card(db: Session, tenant_id: UUID, item_id: int, body: ItemCardTranslate) -> tuple[bool, str]:
    old = db.get(m.InvCard, body.id_card_old)
    new = db.get(m.InvCard, body.id_card)
    rec = db.get(m.InvItemCard, item_id)
    if not old or not new or not rec:
        return False, "Registro no encontrado"
    if {old.tenant_id, new.tenant_id, rec.tenant_id} != {tenant_id}:
        return False, "Registro no encontrado"
    old.hoj_can_tot = max(0, int(old.hoj_can_tot or 0) - 1)
    new.hoj_can_tot = int(new.hoj_can_tot or 0) + 1
    rec.id_card = body.id_card
    db.add(old)
    db.add(new)
    db.add(rec)
    db.commit()
    return True, "Bien actualizado"


def delete_item_card(
    db: Session,
    tenant_id: UUID,
    item_card_id: int,
    id_card: int,
    *,
    operator_id: UUID | None = None,
) -> tuple[bool, str]:
    """`BienesController::destroy` en transacción."""
    try:
        item = db.get(m.InvItemCard, item_card_id)
        card = db.get(m.InvCard, id_card)
        if not item or not card or item.tenant_id != tenant_id or card.tenant_id != tenant_id:
            return False, "Registro no encontrado"
        if item.id_card != id_card:
            return False, "El bien no pertenece a la hoja indicada"
        card.hoj_can_tot = max(0, int(card.hoj_can_tot or 0) - 1)
        if item.id_margesi:
            marg = db.get(m.InvMargesiItem, item.id_margesi)
            if marg and marg.tenant_id == tenant_id:
                marg.inv_num = None
                marg.inv_hoj = None
                marg.inv_sit = None
                marg.inv_con = None
                db.add(marg)
        if operator_id:
            _log_item_audit(
                db,
                tenant_id=tenant_id,
                user_id=operator_id,
                action="delete",
                itemcard_id=item_card_id,
                card_id=id_card,
                inv_num=item.inv_num,
                mar_des=item.mar_des,
            )
        db.delete(item)
        db.add(card)
        db.commit()
        return True, "Bien eliminado con éxito"
    except Exception as e:  # noqa: BLE001
        db.rollback()
        return False, str(e)


# --- list_sbn / margesi ---


def upsert_list_sbn(db: Session, tenant_id: UUID, body: ListSbnWrite) -> m.InvListSbn:
    data = body.model_dump(exclude={"id"})
    if body.id:
        row = db.get(m.InvListSbn, body.id)
        if not row or row.tenant_id != tenant_id:
            raise ValueError("Registro no encontrado")
        for k, v in data.items():
            setattr(row, k, v)
        db.add(row)
        db.commit()
        db.refresh(row)
        return row
    row = m.InvListSbn(tenant_id=tenant_id, **data)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_list_sbn(db: Session, tenant_id: UUID, q: RecordQuery, allowed_cols: set[str]) -> tuple[list[dict], int]:
    col = q.column if q.column in allowed_cols else "code"
    stmt = select(m.InvListSbn).where(m.InvListSbn.tenant_id == tenant_id)
    pattern = _search_like(q)
    if pattern is not None:
        stmt = stmt.where(
            or_(
                m.InvListSbn.code.ilike(pattern),
                m.InvListSbn.cat_des.ilike(pattern),
                m.InvListSbn.cat_clase.ilike(pattern),
                m.InvListSbn.cat_cat.ilike(pattern),
            )
        )
    elif q.value not in (None, ""):
        stmt = stmt.where(getattr(m.InvListSbn, col).ilike(f"%{q.value}%"))
    order_col = q.column_ord or "code"
    if order_col not in allowed_cols | {"id", "created_at"}:
        order_col = "id"
    stmt = stmt.order_by(_ord_clause(m.InvListSbn, order_col, q.ord_tipo))
    rows, total = _paged(db, stmt, q.page, q.per_page)
    return [row_to_dict(r) for r in rows], total


def _bump_list_sbn_cat_ulti_from_margesi(db: Session, tenant_id: UUID, row: m.InvMargesiItem) -> None:
    extra = row.extra if isinstance(row.extra, dict) else {}
    list_id = extra.get("list_sbn_id")
    cat_ultimo = extra.get("cat_ultimo") or row.mar_ccat
    if list_id is None or cat_ultimo is None or str(cat_ultimo).strip() == "":
        return
    sbn = db.get(m.InvListSbn, int(list_id))
    if not sbn or sbn.tenant_id != tenant_id:
        return
    sbn.cat_ulti = str(cat_ultimo).strip()
    db.add(sbn)


_MARGESI_INVENTORY_FIELDS = frozenset({"inv_num", "inv_hoj", "inv_sit", "inv_con"})


def upsert_margesi(db: Session, tenant_id: UUID, body: MargesiWrite) -> m.InvMargesiItem:
    from app.modules.inventory.margesi_mapper import apply_write_payload

    data = body.model_dump(exclude={"id"}, exclude_none=False)
    try:
        if body.id:
            row = db.get(m.InvMargesiItem, body.id)
            if not row or row.tenant_id != tenant_id:
                raise ValueError("Registro no encontrado")
            for k in _MARGESI_INVENTORY_FIELDS:
                data.pop(k, None)
            apply_write_payload(row, data)
            db.add(row)
            _bump_list_sbn_cat_ulti_from_margesi(db, tenant_id, row)
            db.commit()
            db.refresh(row)
            return row
        row = m.InvMargesiItem(tenant_id=tenant_id)
        apply_write_payload(row, data)
        db.add(row)
        _bump_list_sbn_cat_ulti_from_margesi(db, tenant_id, row)
        db.commit()
        db.refresh(row)
        return row
    except Exception:
        db.rollback()
        raise


def list_margesi(db: Session, tenant_id: UUID, q: RecordQuery, allowed_cols: set[str]) -> tuple[list[dict], int]:
    col = q.column if q.column in allowed_cols else "mar_cpat"
    stmt = select(m.InvMargesiItem).where(m.InvMargesiItem.tenant_id == tenant_id)
    pattern = _search_like(q)
    if pattern is not None:
        stmt = stmt.where(
            or_(
                m.InvMargesiItem.inv_num.ilike(pattern),
                m.InvMargesiItem.mar_cpat.ilike(pattern),
                m.InvMargesiItem.mar_des.ilike(pattern),
                m.InvMargesiItem.mar_num.ilike(pattern),
                m.InvMargesiItem.mar_mar.ilike(pattern),
                m.InvMargesiItem.mar_mod.ilike(pattern),
                m.InvMargesiItem.inv_hoj.ilike(pattern),
            )
        )
    elif q.value not in (None, ""):
        stmt = stmt.where(getattr(m.InvMargesiItem, col).ilike(f"%{q.value}%"))
    order_col = q.column_ord or "id"
    if order_col not in allowed_cols | {"id", "created_at"}:
        order_col = "id"
    stmt = stmt.order_by(_ord_clause(m.InvMargesiItem, order_col, q.ord_tipo))
    rows, total = _paged(db, stmt, q.page, q.per_page)
    out: list[dict[str, Any]] = []
    for r in rows:
        d = row_to_dict(r)
        ci = str(d.get("mar_num") or "").strip()
        d["codigo_interno"] = ci or "—"
        d["modelo"] = str(d.get("mar_mod") or "").strip() or "—"
        d["operativo"] = str(d.get("mar_uso") or "").strip() or "—"
        out.append(d)
    return out, total


def paged_meta(total: int, page: int, per_page: int) -> dict[str, int]:
    pages = max(1, math.ceil(total / per_page)) if per_page else 1
    return {"total": total, "page": page, "per_page": per_page, "pages": pages}


_ACTION_LABELS = {"create": "Creación", "update": "Edición", "delete": "Eliminación"}


def list_item_audit_logs(
    db: Session,
    tenant_id: UUID,
    q: AuditLogQuery,
    allowed_cols: set[str],
) -> tuple[list[dict[str, Any]], int]:
    log = m.InvItemAuditLog
    stmt = (
        select(
            log,
            User.full_name.label("user_full_name"),
            User.email.label("user_email"),
            m.InvCard.hoj_num.label("hoj_num"),
        )
        .outerjoin(User, User.id == log.user_id)
        .outerjoin(m.InvCard, m.InvCard.id == log.card_id)
        .where(log.tenant_id == tenant_id)
    )

    if q.action in _ACTION_LABELS:
        stmt = stmt.where(log.action == q.action)

    if q.date_from:
        stmt = stmt.where(log.created_at >= day_start_pe(q.date_from))
    if q.date_to:
        stmt = stmt.where(log.created_at <= day_end_pe(q.date_to))

    like = _search_like(q)
    if like:
        stmt = stmt.where(
            or_(
                log.inv_num.ilike(like),
                log.mar_des.ilike(like),
                log.action.ilike(like),
                User.full_name.ilike(like),
                User.email.ilike(like),
                numeric_column_ilike(m.InvCard.hoj_num, like),
            )
        )
    elif q.value not in (None, ""):
        col = q.column if q.column in allowed_cols else "inv_num"
        if col == "user_full_name":
            stmt = stmt.where(User.full_name.ilike(f"%{q.value}%"))
        elif col == "user_email":
            stmt = stmt.where(User.email.ilike(f"%{q.value}%"))
        elif col == "hoj_num":
            stmt = stmt.where(numeric_column_filter(m.InvCard.hoj_num, q.value))
        elif col in _AUDIT_INT_FILTER_COLS:
            stmt = stmt.where(_where_column_ilike(log, col, q.value, numeric_cols=_AUDIT_INT_FILTER_COLS))
        elif col == "inv_num":
            stmt = stmt.where(m.InvItemAuditLog.inv_num.ilike(f"%{q.value}%"))
        elif hasattr(log, col):
            stmt = stmt.where(getattr(log, col).ilike(f"%{q.value}%"))

    order_col = q.column_ord or "created_at"
    if order_col == "user_full_name":
        stmt = stmt.order_by(_ord_clause(User, "full_name", q.ord_tipo))
    elif order_col == "hoj_num":
        stmt = stmt.order_by(_ord_clause(m.InvCard, "hoj_num", q.ord_tipo))
    elif order_col in {"id", "created_at", "action", "inv_num", "mar_des", "itemcard_id", "card_id"}:
        stmt = stmt.order_by(_ord_clause(log, order_col, q.ord_tipo))
    else:
        stmt = stmt.order_by(desc(log.created_at))

    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int(db.scalar(count_stmt) or 0)
    rows = db.execute(stmt.offset((q.page - 1) * q.per_page).limit(q.per_page)).all()

    out: list[dict[str, Any]] = []
    for row in rows:
        rec = row[0]
        d = row_to_dict(rec)
        d["user_full_name"] = row.user_full_name
        d["user_email"] = row.user_email
        d["hoj_num"] = row.hoj_num
        d["action_label"] = _ACTION_LABELS.get(str(rec.action), str(rec.action))
        d["created_at_pe"] = format_datetime_pe(rec.created_at)
        out.append(d)
    return out, total


_MONTH_LABELS = (
    "Ene",
    "Feb",
    "Mar",
    "Abr",
    "May",
    "Jun",
    "Jul",
    "Ago",
    "Sep",
    "Oct",
    "Nov",
    "Dic",
)


def _month_label(ym: str) -> str:
    year, month = ym.split("-")
    idx = int(month) - 1
    if 0 <= idx < 12:
        return f"{_MONTH_LABELS[idx]} {year}"
    return ym


def _month_bounds(ym: str) -> tuple[date, date]:
    year_s, month_s = ym.split("-")
    year = int(year_s)
    month = int(month_s)
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _iter_months(date_from: date, date_to: date) -> list[str]:
    months: list[str] = []
    cursor = date(date_from.year, date_from.month, 1)
    end = date(date_to.year, date_to.month, 1)
    while cursor <= end:
        months.append(f"{cursor.year:04d}-{cursor.month:02d}")
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return months


def _as_start(dt: date) -> datetime:
    return datetime.combine(dt, time.min, tzinfo=timezone.utc)


def _as_end(dt: date) -> datetime:
    return datetime.combine(dt, time.max, tzinfo=timezone.utc)


def _resolve_dashboard_range(
    date_from: date | None,
    date_to: date | None,
    month: str | None,
) -> tuple[date, date]:
    if month:
        return _month_bounds(month)
    today = datetime.now(timezone.utc).date()
    start = date_from or date(today.year, 1, 1)
    end = date_to or today
    if end < start:
        start, end = end, start
    return start, end


# Baseline user_assigned_bienes: no aplica si «Desde» es posterior al 12/06/2026.
_USER_ASSIGNED_BIENES_DESDE_CUTOFF = date(2026, 6, 12)


def _include_user_assigned_bienes(
    *,
    date_from: date | None,
    month: str | None,
    range_start: date,
) -> bool:
    """Solo sumar asignaciones cuando la fecha «Desde» del filtro no supera el 12/06/2026."""
    if month:
        effective_from = range_start
    elif date_from is not None:
        effective_from = date_from
    else:
        effective_from = range_start
    return effective_from <= _USER_ASSIGNED_BIENES_DESDE_CUTOFF


def inventory_dashboard(
    db: Session,
    tenant_id: UUID,
    establishment_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    month: str | None = None,
) -> dict[str, Any]:
    range_start, range_end = _resolve_dashboard_range(date_from, date_to, month)
    start_dt = _as_start(range_start)
    end_dt = _as_end(range_end)

    bienes_month_expr = func.to_char(func.date_trunc("month", m.InvItemCard.created_at), "YYYY-MM")
    bienes_stmt = (
        select(bienes_month_expr.label("month"), func.count(m.InvItemCard.id).label("cnt"))
        .select_from(m.InvItemCard)
        .join(m.InvCard, m.InvItemCard.id_card == m.InvCard.id)
        .join(m.InvEnvironment, m.InvCard.id_ambiente == m.InvEnvironment.id)
        .where(
            m.InvItemCard.tenant_id == tenant_id,
            m.InvItemCard.created_at >= start_dt,
            m.InvItemCard.created_at <= end_dt,
        )
    )
    if establishment_id:
        bienes_stmt = bienes_stmt.where(m.InvEnvironment.establishment_id == establishment_id)
    bienes_stmt = bienes_stmt.group_by(bienes_month_expr)
    bienes_rows = db.execute(bienes_stmt).all()
    bienes_by_month = {str(row.month): int(row.cnt) for row in bienes_rows if row.month}

    margesi_month_expr = func.to_char(func.date_trunc("month", m.InvMargesiItem.created_at), "YYYY-MM")
    margesi_stmt = select(
        margesi_month_expr.label("month"),
        func.count(m.InvMargesiItem.id).label("cnt"),
    ).where(
        m.InvMargesiItem.tenant_id == tenant_id,
        m.InvMargesiItem.created_at >= start_dt,
        m.InvMargesiItem.created_at <= end_dt,
    )
    if establishment_id:
        linked = (
            select(m.InvItemCard.id)
            .join(m.InvCard, m.InvItemCard.id_card == m.InvCard.id)
            .join(m.InvEnvironment, m.InvCard.id_ambiente == m.InvEnvironment.id)
            .where(
                m.InvItemCard.tenant_id == tenant_id,
                m.InvItemCard.id_margesi == m.InvMargesiItem.id,
                m.InvEnvironment.establishment_id == establishment_id,
            )
        )
        margesi_stmt = margesi_stmt.where(exists(linked))
    margesi_stmt = margesi_stmt.group_by(margesi_month_expr)
    margesi_rows = db.execute(margesi_stmt).all()
    margesi_by_month = {str(row.month): int(row.cnt) for row in margesi_rows if row.month}

    months = _iter_months(range_start, range_end)
    by_month = [
        {
            "month": ym,
            "label": _month_label(ym),
            "bienes": bienes_by_month.get(ym, 0),
            "margesi": margesi_by_month.get(ym, 0),
        }
        for ym in months
    ]

    return {
        "kpis": {
            "bienes_total": sum(bienes_by_month.values()),
            "margesi_total": sum(margesi_by_month.values()),
        },
        "by_month": by_month,
    }


def _user_registration_stats(
    db: Session,
    tenant_id: UUID,
    *,
    establishment_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    month: str | None = None,
) -> dict[str, Any]:
    range_start, range_end = _resolve_dashboard_range(date_from, date_to, month)
    start_dt = _as_start(range_start)
    end_dt = _as_end(range_end)

    log_stmt = (
        select(
            m.InvItemRegistrationLog.user_id,
            User.full_name,
            User.email,
            func.count(m.InvItemRegistrationLog.id).label("cnt"),
        )
        .select_from(m.InvItemRegistrationLog)
        .outerjoin(User, User.id == m.InvItemRegistrationLog.user_id)
        .where(
            m.InvItemRegistrationLog.tenant_id == tenant_id,
            m.InvItemRegistrationLog.created_at >= start_dt,
            m.InvItemRegistrationLog.created_at <= end_dt,
        )
    )
    if establishment_id:
        log_stmt = (
            log_stmt.join(m.InvCard, m.InvItemRegistrationLog.card_id == m.InvCard.id)
            .join(m.InvEnvironment, m.InvCard.id_ambiente == m.InvEnvironment.id)
            .where(m.InvEnvironment.establishment_id == establishment_id)
        )
    log_stmt = log_stmt.group_by(
        m.InvItemRegistrationLog.user_id,
        User.full_name,
        User.email,
    ).order_by(desc("cnt"))
    log_rows = db.execute(log_stmt).all()

    include_assigned = _include_user_assigned_bienes(
        date_from=date_from,
        month=month,
        range_start=range_start,
    )
    assigned_map: dict[str, dict[str, Any]] = {}
    if include_assigned:
        assigned_rows = db.execute(
            select(
                m.InvUserAssignedBienes.user_id,
                User.full_name,
                User.email,
                m.InvUserAssignedBienes.total_bienes,
            )
            .join(User, User.id == m.InvUserAssignedBienes.user_id)
            .where(m.InvUserAssignedBienes.tenant_id == tenant_id)
        ).all()
        assigned_map = {
            str(row.user_id): {
                "full_name": row.full_name,
                "email": row.email,
                "assigned_bienes": int(row.total_bienes or 0),
            }
            for row in assigned_rows
        }

    merged: dict[str, dict[str, Any]] = {}
    for row in log_rows:
        uid = str(row.user_id) if row.user_id else None
        if not uid:
            continue
        assigned = assigned_map.get(uid, {})
        registered = int(row.cnt)
        assigned_bienes = int(assigned.get("assigned_bienes", 0))
        merged[uid] = {
            "user_id": uid,
            "full_name": row.full_name or assigned.get("full_name"),
            "email": row.email or assigned.get("email"),
            "total": registered + assigned_bienes,
        }

    for uid, assigned in assigned_map.items():
        if uid not in merged:
            merged[uid] = {
                "user_id": uid,
                "full_name": assigned.get("full_name"),
                "email": assigned.get("email"),
                "total": int(assigned.get("assigned_bienes", 0)),
            }

    by_user = sorted(merged.values(), key=lambda u: u["total"], reverse=True)

    return {
        "total": sum(u["total"] for u in by_user),
        "by_user": by_user,
    }


def inventory_user_registrations(
    db: Session,
    tenant_id: UUID,
    establishment_id: int | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    month: str | None = None,
) -> dict[str, Any]:
    return _user_registration_stats(
        db,
        tenant_id,
        establishment_id=establishment_id,
        date_from=date_from,
        date_to=date_to,
        month=month,
    )


def get_reporte_aptot_cache_meta(db: Session, tenant_id: UUID) -> dict[str, Any]:
    row = db.get(m.InvReporteAptotCacheMeta, tenant_id)
    if row is None:
        return {
            "status": "pending",
            "row_count": 0,
            "refreshed_at": None,
            "message": "Cache aún no generado",
        }
    return {
        "status": row.status,
        "row_count": int(row.row_count or 0),
        "refreshed_at": row.refreshed_at.isoformat() if row.refreshed_at else None,
        "message": row.message or "",
    }
