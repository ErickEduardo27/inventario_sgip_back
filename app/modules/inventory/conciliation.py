"""Conciliación / desconciliación de patrimonio (Margesi) y bienes inventariados."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import exists, func, or_, select
from sqlalchemy.orm import Session

from app.modules.inventory import models as m
from app.modules.inventory.schemas import (
    ConciliationFilters,
    ImportConciliationRow,
)
from app.modules.inventory.service import _ord_clause, _paged, paged_meta, row_to_dict


def _extra_dict(raw: Any) -> dict[str, Any]:
    return raw if isinstance(raw, dict) else {}


def _extra_text(col: Any, key: str) -> Any:
    return col[key].astext


def _resolve_local_from_ambiente(db: Session, tenant_id: UUID, ambiente_id: int | None) -> str | None:
    if not ambiente_id:
        return None
    env = db.get(m.InvEnvironment, ambiente_id)
    if not env or env.tenant_id != tenant_id:
        return None
    est = db.get(m.InvEstablishment, env.establishment_id)
    return est.description if est else None


def _resolve_margesi_local(db: Session, tenant_id: UUID, row: m.InvMargesiItem) -> str | None:
    code = str(row.amb_cod or "").strip()
    if not code:
        ex = _extra_dict(row.extra)
        code = str(ex.get("codigo_ambiente") or "").strip()
    if not code:
        return None
    env = db.scalar(
        select(m.InvEnvironment).where(
            m.InvEnvironment.tenant_id == tenant_id,
            m.InvEnvironment.code == code,
        )
    )
    if not env:
        return None
    return _resolve_local_from_ambiente(db, tenant_id, int(env.id))


def _margesi_codigo_interno(row: m.InvMargesiItem) -> str | None:
    code = str(row.mar_num or "").strip()
    if code:
        return code
    ex = _extra_dict(row.extra)
    return str(ex.get("codigo_interno") or "").strip() or None


def _margesi_row_public(db: Session, row: m.InvMargesiItem) -> dict[str, Any]:
    d = row_to_dict(row)
    d["mar_num"] = _margesi_codigo_interno(row)
    d["local"] = _resolve_margesi_local(db, row.tenant_id, row)
    return d


def _set_margesi_obs(row: m.InvMargesiItem, observacion: str | None) -> None:
    if observacion is not None:
        row.mar_obs = observacion.strip() or None


def _set_bien_obs(row: m.InvItemCard, observacion: str | None) -> None:
    ex = _extra_dict(row.extra)
    if observacion is not None:
        ex["mar_obs"] = observacion.strip() or None
    row.extra = ex or None


def _sbn_prefix(value: str | None) -> str:
    digits = "".join(c for c in str(value or "") if c.isdigit())
    return digits[:8] if len(digits) >= 8 else digits


def _apply_situacion_margesi(stmt, situacion: str | None):
    if not situacion or situacion == "todos":
        return stmt
    if situacion == "conciliable":
        return stmt.where(m.InvMargesiItem.inv_sit.is_(None))
    if situacion == "no_conciliable":
        return stmt.where(m.InvMargesiItem.inv_sit == "N")
    return stmt


def _apply_situacion_bienes(stmt, situacion: str | None):
    if not situacion or situacion == "todos":
        return stmt
    if situacion == "conciliable":
        return stmt.where(
            m.InvItemCard.id_margesi.is_(None),
            or_(m.InvItemCard.inv_sit.is_(None), m.InvItemCard.inv_sit != "N"),
        )
    if situacion == "no_conciliable":
        return stmt.where(m.InvItemCard.inv_sit == "N")
    return stmt


def _item_card_public(db: Session, tenant_id: UUID, row: m.InvItemCard, card_map: dict[int, str | None]) -> dict[str, Any]:
    ex = _extra_dict(row.extra)
    d = row_to_dict(row)
    d["num_card"] = card_map.get(int(row.id_card))
    d["card_numero"] = d["num_card"]
    d["numero"] = row.inv_num
    d["fisica"] = row.inv_num_1 or row.inv_num_2
    d["codigoSbn"] = row.mar_cpat
    d["descripcion"] = row.mar_des
    d["mar_mar"] = ex.get("mar_mar")
    d["mar_mod"] = ex.get("mar_mod")
    d["mar_obs"] = ex.get("mar_obs")
    d["inv_sit"] = row.inv_sit
    card = db.get(m.InvCard, row.id_card)
    local = None
    if card and card.tenant_id == tenant_id:
        local = _resolve_local_from_ambiente(db, tenant_id, int(card.id_ambiente))
    d["local"] = local
    return d



def _db_env_ids_for_local(db: Session, tenant_id: UUID, local: str) -> list[int]:
    rows = db.scalars(
        select(m.InvEnvironment.id)
        .join(m.InvEstablishment, m.InvEnvironment.establishment_id == m.InvEstablishment.id)
        .where(
            m.InvEnvironment.tenant_id == tenant_id,
            m.InvEstablishment.description.ilike(f"%{local}%"),
        )
    ).all()
    return [int(x) for x in rows]


def _filter_margesi_local(db: Session, tenant_id: UUID, stmt, local: str):
    env_ids = _db_env_ids_for_local(db, tenant_id, local)
    if not env_ids:
        return stmt.where(m.InvMargesiItem.id == -1)
    codes = db.scalars(
        select(m.InvEnvironment.code).where(
            m.InvEnvironment.tenant_id == tenant_id,
            m.InvEnvironment.id.in_(env_ids),
        )
    ).all()
    code_list = [str(c) for c in codes if c]
    if not code_list:
        return stmt.where(m.InvMargesiItem.id == -1)
    return stmt.where(m.InvMargesiItem.amb_cod.in_(code_list))


def list_pending_margesi(
    db: Session,
    tenant_id: UUID,
    f: ConciliationFilters,
) -> tuple[list[dict], int]:
    stmt = select(m.InvMargesiItem).where(
        m.InvMargesiItem.tenant_id == tenant_id,
        m.InvMargesiItem.inv_num.is_(None),
        m.InvMargesiItem.inv_sit.is_(None),
    )
    if f.codigo_interno:
        pattern = f"%{f.codigo_interno}%"
        stmt = stmt.where(
            or_(
                m.InvMargesiItem.mar_num.ilike(pattern),
                m.InvMargesiItem.mar_cpat.ilike(pattern),
            )
        )
    if f.codigo_sbn:
        stmt = stmt.where(m.InvMargesiItem.mar_cpat.ilike(f"%{f.codigo_sbn}%"))
    if f.descripcion:
        stmt = stmt.where(m.InvMargesiItem.mar_des.ilike(f"%{f.descripcion}%"))
    if f.marca:
        stmt = stmt.where(m.InvMargesiItem.mar_mar.ilike(f"%{f.marca}%"))
    if f.modelo:
        stmt = stmt.where(m.InvMargesiItem.mar_mod.ilike(f"%{f.modelo}%"))
    if f.local:
        stmt = _filter_margesi_local(db, tenant_id, stmt, f.local)

    order_col = f.column_ord or "inv_num"
    allowed = {"inv_num", "mar_cpat", "mar_des", "id", "created_at"}
    if order_col not in allowed:
        order_col = "id"
    stmt = stmt.order_by(_ord_clause(m.InvMargesiItem, order_col, f.ord_tipo or "asc"))
    rows, total = _paged(db, stmt, f.page, f.per_page)
    return [_margesi_row_public(db, r) for r in rows], total


def _filter_bienes_local(db: Session, tenant_id: UUID, stmt, local: str):
    card_ids = db.scalars(
        select(m.InvCard.id)
        .join(m.InvEnvironment, m.InvCard.id_ambiente == m.InvEnvironment.id)
        .join(m.InvEstablishment, m.InvEnvironment.establishment_id == m.InvEstablishment.id)
        .where(
            m.InvCard.tenant_id == tenant_id,
            m.InvEstablishment.description.ilike(f"%{local}%"),
        )
    ).all()
    ids = [int(x) for x in card_ids]
    if not ids:
        return stmt.where(m.InvItemCard.id == -1)
    return stmt.where(m.InvItemCard.id_card.in_(ids))


def list_pending_bienes(
    db: Session,
    tenant_id: UUID,
    f: ConciliationFilters,
) -> tuple[list[dict], int]:
    stmt = select(m.InvItemCard).where(
        m.InvItemCard.tenant_id == tenant_id,
        m.InvItemCard.id_margesi.is_(None),
        or_(m.InvItemCard.inv_sit.is_(None), m.InvItemCard.inv_sit == "S"),
    )
    if f.numero_hoja:
        stmt = stmt.join(m.InvCard, m.InvItemCard.id_card == m.InvCard.id).where(
            m.InvCard.hoj_num.ilike(f"%{f.numero_hoja}%")
        )
    if f.numero_inv:
        stmt = stmt.where(m.InvItemCard.inv_num.ilike(f"%{f.numero_inv}%"))
    if f.codigo_sbn:
        stmt = stmt.where(m.InvItemCard.mar_cpat.ilike(f"%{f.codigo_sbn}%"))
    if f.descripcion:
        stmt = stmt.where(m.InvItemCard.mar_des.ilike(f"%{f.descripcion}%"))
    if f.marca:
        stmt = stmt.where(_extra_text(m.InvItemCard.extra, "mar_mar").ilike(f"%{f.marca}%"))
    if f.modelo:
        stmt = stmt.where(_extra_text(m.InvItemCard.extra, "mar_mod").ilike(f"%{f.modelo}%"))
    if f.local:
        stmt = _filter_bienes_local(db, tenant_id, stmt, f.local)

    order_col = f.column_ord or "id"
    allowed = {"id", "inv_num", "mar_cpat", "mar_des", "created_at", "id_margesi"}
    if order_col not in allowed:
        order_col = "id"
    stmt = stmt.order_by(_ord_clause(m.InvItemCard, order_col, f.ord_tipo or "asc"))
    rows, total = _paged(db, stmt, f.page, f.per_page)
    if not rows:
        return [], total
    card_ids = {int(r.id_card) for r in rows}
    card_map: dict[int, str | None] = {}
    for c in db.scalars(select(m.InvCard).where(m.InvCard.tenant_id == tenant_id, m.InvCard.id.in_(card_ids))):
        card_map[int(c.id)] = c.hoj_num
    return [_item_card_public(db, tenant_id, r, card_map) for r in rows], total


def list_conciliated_bienes(
    db: Session,
    tenant_id: UUID,
    f: ConciliationFilters,
) -> tuple[list[dict], int]:
    stmt = select(m.InvItemCard).where(
        m.InvItemCard.tenant_id == tenant_id,
        m.InvItemCard.id_margesi.isnot(None),
        m.InvItemCard.inv_sit == "C",
    )
    if f.numero_hoja:
        stmt = stmt.join(m.InvCard, m.InvItemCard.id_card == m.InvCard.id).where(
            m.InvCard.hoj_num.ilike(f"%{f.numero_hoja}%")
        )
    if f.numero_inv:
        stmt = stmt.where(m.InvItemCard.inv_num.ilike(f"%{f.numero_inv}%"))
    if f.codigo_sbn:
        stmt = stmt.where(m.InvItemCard.mar_cpat.ilike(f"%{f.codigo_sbn}%"))
    if f.descripcion:
        stmt = stmt.where(m.InvItemCard.mar_des.ilike(f"%{f.descripcion}%"))
    if f.local:
        stmt = _filter_bienes_local(db, tenant_id, stmt, f.local)

    order_col = f.column_ord or "id"
    stmt = stmt.order_by(_ord_clause(m.InvItemCard, order_col, f.ord_tipo or "desc"))
    rows, total = _paged(db, stmt, f.page, f.per_page)
    if not rows:
        return [], total
    card_ids = {int(r.id_card) for r in rows}
    card_map: dict[int, str | None] = {}
    for c in db.scalars(select(m.InvCard).where(m.InvCard.tenant_id == tenant_id, m.InvCard.id.in_(card_ids))):
        card_map[int(c.id)] = c.hoj_num
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _item_card_public(db, tenant_id, r, card_map)
        marg = db.get(m.InvMargesiItem, r.id_margesi) if r.id_margesi else None
        if marg and marg.tenant_id == tenant_id:
            d["margesi_id"] = marg.id
            d["margesi_codigo_interno"] = _margesi_codigo_interno(marg)
            d["margesi_descripcion"] = marg.mar_des
        out.append(d)
    return out, total


def list_no_conciliables(
    db: Session,
    tenant_id: UUID,
    f: ConciliationFilters,
) -> tuple[list[dict], int]:
    stmt = select(m.InvItemCard).where(
        m.InvItemCard.tenant_id == tenant_id,
        m.InvItemCard.inv_sit == "N",
    )
    if f.numero_hoja:
        stmt = stmt.join(m.InvCard, m.InvItemCard.id_card == m.InvCard.id).where(
            m.InvCard.hoj_num.ilike(f"%{f.numero_hoja}%")
        )
    if f.numero_inv:
        stmt = stmt.where(m.InvItemCard.inv_num.ilike(f"%{f.numero_inv}%"))
    if f.codigo_sbn:
        stmt = stmt.where(m.InvItemCard.mar_cpat.ilike(f"%{f.codigo_sbn}%"))
    if f.descripcion:
        stmt = stmt.where(m.InvItemCard.mar_des.ilike(f"%{f.descripcion}%"))
    if f.local:
        stmt = _filter_bienes_local(db, tenant_id, stmt, f.local)

    stmt = stmt.order_by(_ord_clause(m.InvItemCard, f.column_ord or "id", f.ord_tipo or "desc"))
    rows, total = _paged(db, stmt, f.page, f.per_page)
    if not rows:
        return [], total
    card_ids = {int(r.id_card) for r in rows}
    card_map: dict[int, str | None] = {}
    for c in db.scalars(select(m.InvCard).where(m.InvCard.tenant_id == tenant_id, m.InvCard.id.in_(card_ids))):
        card_map[int(c.id)] = c.hoj_num
    return [_item_card_public(db, tenant_id, r, card_map) for r in rows], total


def list_conciliated_margesi(
    db: Session,
    tenant_id: UUID,
    f: ConciliationFilters,
) -> tuple[list[dict], int]:
    stmt = select(m.InvMargesiItem).where(
        m.InvMargesiItem.tenant_id == tenant_id,
        m.InvMargesiItem.inv_sit == "C",
        m.InvMargesiItem.inv_num.isnot(None),
    )
    if f.codigo_interno:
        pattern = f"%{f.codigo_interno}%"
        stmt = stmt.where(
            or_(
                m.InvMargesiItem.mar_num.ilike(pattern),
                m.InvMargesiItem.mar_cpat.ilike(pattern),
            )
        )
    if f.codigo_sbn:
        stmt = stmt.where(m.InvMargesiItem.mar_cpat.ilike(f"%{f.codigo_sbn}%"))
    if f.descripcion:
        stmt = stmt.where(m.InvMargesiItem.mar_des.ilike(f"%{f.descripcion}%"))
    if f.local:
        stmt = _filter_margesi_local(db, tenant_id, stmt, f.local)
    stmt = stmt.order_by(_ord_clause(m.InvMargesiItem, f.column_ord or "id", f.ord_tipo or "desc"))
    rows, total = _paged(db, stmt, f.page, f.per_page)
    return [_margesi_row_public(db, r) for r in rows], total


def list_no_conciliation_margesi(
    db: Session,
    tenant_id: UUID,
    f: ConciliationFilters,
) -> tuple[list[dict], int]:
    stmt = select(m.InvMargesiItem).where(
        m.InvMargesiItem.tenant_id == tenant_id,
        m.InvMargesiItem.inv_num.is_(None),
    )
    stmt = _apply_situacion_margesi(stmt, f.situacion)
    if f.codigo_interno:
        pattern = f"%{f.codigo_interno}%"
        stmt = stmt.where(
            or_(
                m.InvMargesiItem.mar_num.ilike(pattern),
                m.InvMargesiItem.mar_cpat.ilike(pattern),
            )
        )
    if f.codigo_sbn:
        stmt = stmt.where(m.InvMargesiItem.mar_cpat.ilike(f"%{f.codigo_sbn}%"))
    if f.descripcion:
        stmt = stmt.where(m.InvMargesiItem.mar_des.ilike(f"%{f.descripcion}%"))
    if f.local:
        stmt = _filter_margesi_local(db, tenant_id, stmt, f.local)
    stmt = stmt.order_by(_ord_clause(m.InvMargesiItem, f.column_ord or "id", f.ord_tipo or "asc"))
    rows, total = _paged(db, stmt, f.page, f.per_page)
    return [_margesi_row_public(db, r) for r in rows], total


def list_no_conciliation_bienes(
    db: Session,
    tenant_id: UUID,
    f: ConciliationFilters,
) -> tuple[list[dict], int]:
    stmt = select(m.InvItemCard).where(m.InvItemCard.tenant_id == tenant_id)
    if f.situacion == "no_conciliable":
        stmt = stmt.where(m.InvItemCard.inv_sit == "N")
    elif f.situacion == "conciliable":
        stmt = stmt.where(
            m.InvItemCard.id_margesi.is_(None),
            or_(m.InvItemCard.inv_sit.is_(None), m.InvItemCard.inv_sit == "S"),
        )
    else:
        stmt = stmt.where(m.InvItemCard.id_margesi.is_(None))
    if f.numero_hoja:
        stmt = stmt.join(m.InvCard, m.InvItemCard.id_card == m.InvCard.id).where(
            m.InvCard.hoj_num.ilike(f"%{f.numero_hoja}%")
        )
    if f.numero_inv:
        stmt = stmt.where(m.InvItemCard.inv_num.ilike(f"%{f.numero_inv}%"))
    if f.codigo_sbn:
        stmt = stmt.where(m.InvItemCard.mar_cpat.ilike(f"%{f.codigo_sbn}%"))
    if f.descripcion:
        stmt = stmt.where(m.InvItemCard.mar_des.ilike(f"%{f.descripcion}%"))
    if f.local:
        stmt = _filter_bienes_local(db, tenant_id, stmt, f.local)
    stmt = stmt.order_by(_ord_clause(m.InvItemCard, f.column_ord or "id", f.ord_tipo or "asc"))
    rows, total = _paged(db, stmt, f.page, f.per_page)
    if not rows:
        return [], total
    card_ids = {int(r.id_card) for r in rows}
    card_map: dict[int, str | None] = {}
    for c in db.scalars(select(m.InvCard).where(m.InvCard.tenant_id == tenant_id, m.InvCard.id.in_(card_ids))):
        card_map[int(c.id)] = c.hoj_num
    return [_item_card_public(db, tenant_id, r, card_map) for r in rows], total


def list_desconciliacion_sbn_margesi(
    db: Session,
    tenant_id: UUID,
    f: ConciliationFilters,
) -> tuple[list[dict], int]:
    stmt = select(m.InvMargesiItem).where(
        m.InvMargesiItem.tenant_id == tenant_id,
        m.InvMargesiItem.inv_num.isnot(None),
    )
    if f.codigo_interno:
        pattern = f"%{f.codigo_interno}%"
        stmt = stmt.where(m.InvMargesiItem.mar_num.ilike(pattern))
    if f.codigo_sbn:
        stmt = stmt.where(m.InvMargesiItem.mar_cpat.ilike(f"%{f.codigo_sbn}%"))
    if f.descripcion:
        stmt = stmt.where(m.InvMargesiItem.mar_des.ilike(f"%{f.descripcion}%"))
    if f.local:
        stmt = _filter_margesi_local(db, tenant_id, stmt, f.local)
    stmt = stmt.order_by(_ord_clause(m.InvMargesiItem, f.column_ord or "id", f.ord_tipo or "desc"))
    rows, total = _paged(db, stmt, f.page, f.per_page)
    return [_margesi_row_public(db, r) for r in rows], total


def list_desconciliacion_sbn_bienes(
    db: Session,
    tenant_id: UUID,
    f: ConciliationFilters,
) -> tuple[list[dict], int]:
    stmt = select(m.InvItemCard).where(
        m.InvItemCard.tenant_id == tenant_id,
        m.InvItemCard.id_margesi.isnot(None),
    )
    if f.numero_hoja:
        stmt = stmt.join(m.InvCard, m.InvItemCard.id_card == m.InvCard.id).where(
            m.InvCard.hoj_num.ilike(f"%{f.numero_hoja}%")
        )
    if f.numero_inv:
        stmt = stmt.where(m.InvItemCard.inv_num.ilike(f"%{f.numero_inv}%"))
    if f.codigo_sbn:
        stmt = stmt.where(m.InvItemCard.mar_cpat.ilike(f"%{f.codigo_sbn}%"))
    if f.descripcion:
        stmt = stmt.where(m.InvItemCard.mar_des.ilike(f"%{f.descripcion}%"))
    if f.local:
        stmt = _filter_bienes_local(db, tenant_id, stmt, f.local)
    stmt = stmt.order_by(_ord_clause(m.InvItemCard, f.column_ord or "id", f.ord_tipo or "desc"))
    rows, total = _paged(db, stmt, f.page, f.per_page)
    if not rows:
        return [], total
    card_ids = {int(r.id_card) for r in rows}
    card_map: dict[int, str | None] = {}
    for c in db.scalars(select(m.InvCard).where(m.InvCard.tenant_id == tenant_id, m.InvCard.id.in_(card_ids))):
        card_map[int(c.id)] = c.hoj_num
    out: list[dict[str, Any]] = []
    for r in rows:
        d = _item_card_public(db, tenant_id, r, card_map)
        marg = db.get(m.InvMargesiItem, r.id_margesi) if r.id_margesi else None
        if marg and marg.tenant_id == tenant_id:
            d["margesi_id"] = marg.id
            d["margesi_codigo_interno"] = _margesi_codigo_interno(marg)
        out.append(d)
    return out, total


def conciliar_pair(
    db: Session,
    tenant_id: UUID,
    margesi_id: int,
    bien_id: int,
    *,
    inv_con: str = "1",
    inv_hoj: str | None = None,
) -> tuple[bool, str]:
    try:
        marg = db.get(m.InvMargesiItem, margesi_id)
        bien = db.get(m.InvItemCard, bien_id)
        if not marg or marg.tenant_id != tenant_id:
            return False, "No se encontró el margesi."
        if not bien or bien.tenant_id != tenant_id:
            return False, "No se encontró el bien."
        if bien.id_margesi:
            return False, "El bien ya está conciliado."
        if marg.inv_num or marg.inv_sit == "C":
            return False, "El margesi ya está conciliado."
        if marg.inv_sit == "N":
            return False, "El margesi está marcado como no conciliable."
        if bien.inv_sit == "N":
            return False, "El bien está marcado como no conciliable."
        if bien.inv_sit not in (None, "S"):
            return False, "El bien no está pendiente de conciliación (debe estar en situación S)."

        mar_num = _margesi_codigo_interno(marg)
        extra = dict(bien.extra or {})
        if mar_num:
            extra["mar_npri"] = mar_num

        marg.inv_num = bien.inv_num
        marg.inv_sit = "C"
        marg.inv_con = inv_con
        marg.inv_hoj = inv_hoj if inv_hoj is not None else "1"

        bien.mar_num = mar_num
        bien.inv_sit = "C"
        bien.inv_con = inv_con
        bien.id_margesi = marg.id
        bien.extra = extra or None

        db.add(marg)
        db.add(bien)
        db.commit()
        return True, "Bienes conciliados"
    except Exception:  # noqa: BLE001
        db.rollback()
        return False, "Ocurrió un error al procesar la solicitud."


def conciliar_pair_sbn(
    db: Session,
    tenant_id: UUID,
    margesi_id: int,
    bien_id: int,
    numero_hoja: str,
    codigo_sbn: str,
) -> tuple[bool, str]:
    codigo = "".join(c for c in str(codigo_sbn or "") if c.isdigit())
    if len(codigo) != 12:
        return False, "El código SBN debe tener 12 dígitos numéricos."
    marg = db.get(m.InvMargesiItem, margesi_id)
    bien = db.get(m.InvItemCard, bien_id)
    if not marg or marg.tenant_id != tenant_id:
        return False, "No se encontró el margesi."
    if not bien or bien.tenant_id != tenant_id:
        return False, "No se encontró el bien."
    if _sbn_prefix(bien.mar_cpat) != _sbn_prefix(marg.mar_cpat):
        return False, "Los primeros 8 dígitos del SBN del bien y del Margesi no coinciden."
    try:
        if bien.id_margesi:
            return False, "El bien ya está conciliado."
        if marg.inv_num or marg.inv_sit == "C":
            return False, "El margesi ya está conciliado."
        if marg.inv_sit == "N" or bien.inv_sit == "N":
            return False, "Registro marcado como no conciliable."
        if bien.inv_sit not in (None, "S"):
            return False, "El bien no está pendiente de conciliación."

        mar_num = _margesi_codigo_interno(marg)
        extra = dict(bien.extra or {})
        if mar_num:
            extra["mar_npri"] = mar_num

        marg.inv_num = bien.inv_num
        marg.inv_sit = "C"
        marg.inv_con = "1"
        marg.inv_hoj = numero_hoja.strip() or None

        bien.mar_num = mar_num
        bien.mar_cpat = codigo
        bien.inv_sit = "C"
        bien.inv_con = "1"
        bien.id_margesi = marg.id
        bien.extra = extra or None

        db.add(marg)
        db.add(bien)
        db.commit()
        return True, "Bienes conciliados (SBN)"
    except Exception:  # noqa: BLE001
        db.rollback()
        return False, "Ocurrió un error al procesar la solicitud."


def desconciliar_item(db: Session, tenant_id: UUID, item_id: int) -> tuple[bool, str]:
    try:
        bien = db.get(m.InvItemCard, item_id)
        if not bien or bien.tenant_id != tenant_id:
            return False, "No se encontró el bien."
        if not bien.id_margesi:
            return False, "El bien no está conciliado."

        marg = db.get(m.InvMargesiItem, bien.id_margesi)
        if not marg or marg.tenant_id != tenant_id:
            return False, "No se encontró el margesi."

        marg.inv_num = None
        marg.inv_sit = None
        marg.inv_con = None
        marg.inv_hoj = None

        extra = dict(bien.extra or {})
        extra.pop("mar_npri", None)
        bien.id_margesi = None
        bien.mar_num = None
        bien.inv_sit = "S"
        bien.inv_con = None
        bien.extra = extra or None

        db.add(marg)
        db.add(bien)
        db.commit()
        return True, "Bienes desconciliados"
    except Exception:  # noqa: BLE001
        db.rollback()
        return False, "Ocurrió un error al procesar la solicitud."


def desconciliar_pair_sbn(
    db: Session,
    tenant_id: UUID,
    item_id: int,
    margesi_id: int,
) -> tuple[bool, str]:
    try:
        bien = db.get(m.InvItemCard, item_id)
        if not bien or bien.tenant_id != tenant_id:
            return False, "No se encontró el bien."
        if not bien.id_margesi:
            return False, "El bien no está conciliado."
        if int(bien.id_margesi) != int(margesi_id):
            return False, "El bien no corresponde al Margesi seleccionado."

        marg = db.get(m.InvMargesiItem, margesi_id)
        if not marg or marg.tenant_id != tenant_id:
            return False, "No se encontró el margesi."

        marg.inv_num = None
        marg.inv_sit = None
        marg.inv_con = None
        marg.inv_hoj = None

        extra = dict(bien.extra or {})
        extra.pop("mar_npri", None)
        bien.id_margesi = None
        bien.mar_cpat = None
        bien.mar_num = None
        bien.inv_sit = None
        bien.inv_con = None
        bien.extra = extra or None

        db.add(marg)
        db.add(bien)
        db.commit()
        return True, "Bienes desconciliados (SBN)"
    except Exception:  # noqa: BLE001
        db.rollback()
        return False, "Ocurrió un error al procesar la solicitud."


def mark_no_conciliable(db: Session, tenant_id: UUID, item_id: int) -> tuple[bool, str]:
    return mark_no_conciliable_entity(db, tenant_id, "bien", item_id, None)


def unmark_no_conciliable(db: Session, tenant_id: UUID, item_id: int) -> tuple[bool, str]:
    return mark_conciliable_entity(db, tenant_id, "bien", item_id, None)


def mark_no_conciliable_entity(
    db: Session,
    tenant_id: UUID,
    tipo: str,
    entity_id: int,
    observacion: str | None,
) -> tuple[bool, str]:
    try:
        if tipo == "margesi":
            row = db.get(m.InvMargesiItem, entity_id)
            if not row or row.tenant_id != tenant_id:
                return False, "No se encontró el margesi."
            if row.inv_num:
                return False, "No se puede marcar: el margesi ya está conciliado."
            row.inv_sit = "N"
            _set_margesi_obs(row, observacion)
            db.add(row)
        elif tipo == "bien":
            row = db.get(m.InvItemCard, entity_id)
            if not row or row.tenant_id != tenant_id:
                return False, "No se encontró el bien."
            if row.id_margesi:
                return False, "No se puede marcar: el bien ya está conciliado."
            row.inv_sit = "N"
            _set_bien_obs(row, observacion)
            db.add(row)
        else:
            return False, "Tipo de registro no válido."
        db.commit()
        return True, "Registro marcado como no conciliable"
    except Exception:  # noqa: BLE001
        db.rollback()
        return False, "Ocurrió un error al procesar la solicitud."


def mark_conciliable_entity(
    db: Session,
    tenant_id: UUID,
    tipo: str,
    entity_id: int,
    observacion: str | None,
) -> tuple[bool, str]:
    try:
        if tipo == "margesi":
            row = db.get(m.InvMargesiItem, entity_id)
            if not row or row.tenant_id != tenant_id:
                return False, "No se encontró el margesi."
            row.inv_sit = None
            _set_margesi_obs(row, observacion)
            db.add(row)
        elif tipo == "bien":
            row = db.get(m.InvItemCard, entity_id)
            if not row or row.tenant_id != tenant_id:
                return False, "No se encontró el bien."
            if row.id_margesi:
                return False, "No se puede habilitar: el bien ya está conciliado."
            row.inv_sit = "S"
            _set_bien_obs(row, observacion)
            db.add(row)
        else:
            return False, "Tipo de registro no válido."
        db.commit()
        return True, "Registro habilitado para conciliación"
    except Exception:  # noqa: BLE001
        db.rollback()
        return False, "Ocurrió un error al procesar la solicitud."


def import_conciliar_rows(
    db: Session,
    tenant_id: UUID,
    rows: list[ImportConciliationRow],
) -> dict[str, Any]:
    registrados: list[dict[str, Any]] = []
    no_registrados: list[dict[str, Any]] = []
    for row in rows:
        inv_con = getattr(row, "inv_con", None) or "1"
        ok, msg = conciliar_pair(
            db,
            tenant_id,
            row.margesi_id,
            row.bien_id,
            inv_con=inv_con,
        )
        entry = {"margesi_id": row.margesi_id, "bien_id": row.bien_id, "message": msg}
        if ok:
            registrados.append(entry)
        else:
            no_registrados.append(entry)
    success = len(registrados) > 0
    if len(no_registrados) > 0 and len(registrados) == 0:
        success = False
    return {
        "success": success,
        "message": "Importación completada" if success else "No se pudo conciliar ningún registro",
        "registrados": registrados,
        "no_registrados": no_registrados,
    }


def import_desconciliar_rows(
    db: Session,
    tenant_id: UUID,
    item_ids: list[int],
) -> dict[str, Any]:
    registrados: list[dict[str, Any]] = []
    no_registrados: list[dict[str, Any]] = []
    for item_id in item_ids:
        ok, msg = desconciliar_item(db, tenant_id, item_id)
        entry = {"item_id": item_id, "message": msg}
        if ok:
            registrados.append(entry)
        else:
            no_registrados.append(entry)
    success = len(registrados) > 0
    if len(no_registrados) > 0 and len(registrados) == 0:
        success = False
    return {
        "success": success,
        "message": "Desconciliación completada" if success else "No se pudo desconciliar ningún registro",
        "registrados": registrados,
        "no_registrados": no_registrados,
    }


def import_no_conciliable_rows(
    db: Session,
    tenant_id: UUID,
    rows: list[tuple[str | None, str | None, str | None]],
) -> dict[str, Any]:
    registrados: list[dict[str, Any]] = []
    no_registrados: list[dict[str, Any]] = []
    for codigo_interno, inv_num, observacion in rows:
        ok = False
        msg = "No se encontró registro aplicable"
        if codigo_interno:
            marg = db.scalar(
                select(m.InvMargesiItem).where(
                    m.InvMargesiItem.tenant_id == tenant_id,
                    m.InvMargesiItem.inv_num.is_(None),
                    m.InvMargesiItem.inv_sit.is_(None),
                    m.InvMargesiItem.mar_num == codigo_interno.strip(),
                )
            )
            if marg:
                ok, msg = mark_no_conciliable_entity(
                    db, tenant_id, "margesi", int(marg.id), observacion
                )
        if not ok and inv_num:
            bien = db.scalar(
                select(m.InvItemCard).where(
                    m.InvItemCard.tenant_id == tenant_id,
                    m.InvItemCard.inv_num == inv_num.strip(),
                    m.InvItemCard.id_margesi.is_(None),
                    m.InvItemCard.inv_sit == "S",
                )
            )
            if bien:
                ok, msg = mark_no_conciliable_entity(
                    db, tenant_id, "bien", int(bien.id), observacion
                )
        entry = {
            "codigo_interno": codigo_interno,
            "inv_num": inv_num,
            "message": msg,
        }
        if ok:
            registrados.append(entry)
        else:
            no_registrados.append(entry)
    success = len(registrados) > 0
    return {
        "success": success,
        "message": "Importación completada" if success else "No se marcó ningún registro",
        "registrados": registrados,
        "no_registrados": no_registrados,
    }


def match_import_conciliation(
    db: Session,
    tenant_id: UUID,
    codigo_interno: str | None,
    inv_num: str | None,
    mar_cpat: str | None,
) -> tuple[int | None, int | None, str | None]:
    margesi_id: int | None = None
    bien_id: int | None = None

    if codigo_interno:
        marg = db.scalar(
            select(m.InvMargesiItem).where(
                m.InvMargesiItem.tenant_id == tenant_id,
                m.InvMargesiItem.inv_num.is_(None),
                m.InvMargesiItem.inv_sit.is_(None),
                m.InvMargesiItem.mar_num == codigo_interno.strip(),
            )
        )
        if marg:
            margesi_id = int(marg.id)
    if mar_cpat and not margesi_id:
        marg = db.scalar(
            select(m.InvMargesiItem).where(
                m.InvMargesiItem.tenant_id == tenant_id,
                m.InvMargesiItem.inv_num.is_(None),
                m.InvMargesiItem.inv_sit.is_(None),
                m.InvMargesiItem.mar_cpat == mar_cpat.strip(),
            )
        )
        if marg:
            margesi_id = int(marg.id)

    if inv_num:
        bien = db.scalar(
            select(m.InvItemCard).where(
                m.InvItemCard.tenant_id == tenant_id,
                m.InvItemCard.id_margesi.is_(None),
                m.InvItemCard.inv_num == inv_num.strip(),
                m.InvItemCard.inv_sit == "S",
            )
        )
        if bien:
            bien_id = int(bien.id)

    reason: str | None = None
    if margesi_id and bien_id:
        marg = db.get(m.InvMargesiItem, margesi_id)
        bien = db.get(m.InvItemCard, bien_id)
        if marg and marg.inv_sit == "N":
            reason = "Margesi marcado como no conciliable"
        elif bien and bien.inv_sit == "N":
            reason = "Bien marcado como no conciliable"
        elif marg and marg.inv_sit is not None:
            reason = "Margesi no está pendiente de conciliación"
        elif bien and bien.inv_sit != "S":
            reason = "El bien debe estar en situación S (sobrante)"
    elif codigo_interno or inv_num:
        reason = "Par no encontrado o no cumple condiciones de conciliación"

    return margesi_id, bien_id, reason


def match_import_conciliation_sbn(
    db: Session,
    tenant_id: UUID,
    codigo_interno: str | None,
    inv_num: str | None,
    mar_cpat: str | None,
) -> tuple[int | None, int | None, str | None]:
    margesi_id, bien_id, reason = match_import_conciliation(
        db, tenant_id, codigo_interno, inv_num, mar_cpat
    )
    if not margesi_id or not bien_id:
        return margesi_id, bien_id, reason
    marg = db.get(m.InvMargesiItem, margesi_id)
    bien = db.get(m.InvItemCard, bien_id)
    if marg and bien and _sbn_prefix(bien.mar_cpat) != _sbn_prefix(marg.mar_cpat):
        return margesi_id, bien_id, "Prefijo SBN (8 dígitos) no coincide"
    codigo = "".join(c for c in str(marg.mar_cpat or "") if c.isdigit()) if marg else ""
    if len(codigo) != 12:
        return margesi_id, bien_id, "Código SBN del Margesi debe tener 12 dígitos"
    return margesi_id, bien_id, None
