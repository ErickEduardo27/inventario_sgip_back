"""Servicio Conciliación Margesi: inconsistencias, candidatos, confirmación y auditoría."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, load_only

from app.core.inventory_numbers import format_inv_num
from app.modules.inventory import models as m
from app.modules.inventory.conciliacion_margesi_engine import (
    MatchProposal,
    classify_tier,
    normalize_sbn,
    normalize_serie,
    score_pair,
    year_from_date,
)
from app.modules.inventory.conciliation import (
    _extra_dict,
    _margesi_codigo_interno,
    _schedule_inventory_caches_refresh,
)
from app.modules.inventory.service import (
    _margesi_faltantes_inv_sit_clause,
)

# Límites para no materializar 150k+ filas en memoria.
FALTANTES_MATCH_LIMIT = 2500
BIENES_MATCH_LIMIT = 12000


def _bien_extra(row: m.InvItemCard) -> dict[str, Any]:
    return _extra_dict(row.extra)


def _bien_field(row: m.InvItemCard, key: str) -> str:
    ex = _bien_extra(row)
    return str(ex.get(key) or "").strip()


@dataclass
class _MatchCtx:
    """Caches en memoria para evitar N+1 durante el scoring."""

    cards: dict[int, m.InvCard] = field(default_factory=dict)
    env_by_id: dict[int, m.InvEnvironment] = field(default_factory=dict)
    est_by_id: dict[int, m.InvEstablishment] = field(default_factory=dict)
    est_by_code: dict[str, m.InvEstablishment] = field(default_factory=dict)
    env_by_code: dict[str, m.InvEnvironment] = field(default_factory=dict)
    person_name: dict[int, str] = field(default_factory=dict)

    def local_code_for_card(self, card: m.InvCard | None) -> str:
        if not card:
            return ""
        env = self.env_by_id.get(int(card.id_ambiente))
        if not env:
            return ""
        est = self.est_by_id.get(int(env.establishment_id))
        return str(est.code or "").strip() if est else ""

    def local_label_for_card(self, card: m.InvCard | None) -> str:
        if not card:
            return ""
        env = self.env_by_id.get(int(card.id_ambiente))
        if not env:
            return ""
        est = self.est_by_id.get(int(env.establishment_id))
        return str(est.description or est.code or "").strip() if est else ""

    def local_label_for_margesi(self, row: m.InvMargesiItem) -> str:
        code = str(row.amb_cod or "").strip()
        if not code:
            ex = _extra_dict(row.extra)
            code = str(ex.get("codigo_ambiente") or "").strip()
        if not code:
            return ""
        env = self.env_by_code.get(code.upper()) or self.env_by_code.get(code)
        if not env:
            return ""
        est = self.est_by_id.get(int(env.establishment_id))
        return str(est.description or est.code or "").strip() if est else ""

    def person(self, person_id: int | None) -> str:
        if not person_id:
            return ""
        return self.person_name.get(int(person_id), "")


def _build_match_ctx(
    db: Session,
    tenant_id: UUID,
    bienes: list[m.InvItemCard],
    faltantes: list[m.InvMargesiItem],
) -> _MatchCtx:
    ctx = _MatchCtx()
    card_ids = {int(b.id_card) for b in bienes if b.id_card}
    if card_ids:
        for c in db.scalars(select(m.InvCard).where(m.InvCard.id.in_(card_ids))):
            ctx.cards[int(c.id)] = c

    env_ids = {int(c.id_ambiente) for c in ctx.cards.values() if c.id_ambiente}
    amb_codes = {
        str(r.amb_cod or "").strip()
        for r in faltantes
        if str(r.amb_cod or "").strip()
    }
    if env_ids or amb_codes:
        env_stmt = select(m.InvEnvironment).where(m.InvEnvironment.tenant_id == tenant_id)
        if env_ids and amb_codes:
            env_stmt = env_stmt.where(
                or_(
                    m.InvEnvironment.id.in_(env_ids),
                    m.InvEnvironment.code.in_(list(amb_codes)),
                )
            )
        elif env_ids:
            env_stmt = env_stmt.where(m.InvEnvironment.id.in_(env_ids))
        else:
            env_stmt = env_stmt.where(m.InvEnvironment.code.in_(list(amb_codes)))
        for env in db.scalars(env_stmt):
            ctx.env_by_id[int(env.id)] = env
            code = str(env.code or "").strip()
            if code:
                ctx.env_by_code[code] = env
                ctx.env_by_code[code.upper()] = env

    est_ids = {int(e.establishment_id) for e in ctx.env_by_id.values() if e.establishment_id}
    if est_ids:
        for est in db.scalars(
            select(m.InvEstablishment).where(
                m.InvEstablishment.tenant_id == tenant_id,
                m.InvEstablishment.id.in_(est_ids),
            )
        ):
            ctx.est_by_id[int(est.id)] = est
            code = str(est.code or "").strip()
            if code:
                ctx.est_by_code[code.upper()] = est

    person_ids = {int(c.id_usuario) for c in ctx.cards.values() if c.id_usuario}
    if person_ids:
        for p in db.scalars(
            select(m.InvPerson).where(
                m.InvPerson.tenant_id == tenant_id,
                m.InvPerson.id.in_(person_ids),
            )
        ):
            ctx.person_name[int(p.id)] = str(p.name or p.number or "").strip()
    return ctx


def _margesi_snapshot_ctx(row: m.InvMargesiItem, ctx: _MatchCtx) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "mar_num": _margesi_codigo_interno(row),
        "mar_cpat": row.mar_cpat,
        "mar_des": row.mar_des,
        "mar_mar": row.mar_mar,
        "mar_mod": row.mar_mod,
        "mar_ser": row.mar_ser,
        "mar_est": row.mar_est,
        "amb_cod": row.amb_cod,
        "local": ctx.local_label_for_margesi(row),
        "responsable": str(row.usuario_libre or row.usu_cod or row.usu_resp_cod or "").strip(),
        "inv_sit": row.inv_sit,
        "inv_num": row.inv_num,
        "inv_con": row.inv_con,
        "fecha_adquisicion": row.mar_ing_fdadq.isoformat() if row.mar_ing_fdadq else None,
        "anio_adquisicion": year_from_date(row.mar_ing_fdadq),
    }


def _bien_snapshot_ctx(row: m.InvItemCard, card: m.InvCard | None, ctx: _MatchCtx) -> dict[str, Any]:
    ex = _bien_extra(row)
    return {
        "id": int(row.id),
        "inv_num": format_inv_num(row.inv_num) if row.inv_num is not None else None,
        "mar_cpat": row.mar_cpat,
        "mar_des": row.mar_des,
        "mar_mar": ex.get("mar_mar") or "",
        "mar_mod": ex.get("mar_mod") or "",
        "mar_ser": ex.get("mar_ser") or "",
        "mar_est": ex.get("mar_est") or "",
        "inv_sit": row.inv_sit,
        "id_margesi": row.id_margesi,
        "hoj_num": format_inv_num(card.hoj_num) if card and card.hoj_num is not None else None,
        "local": ctx.local_label_for_card(card),
        "local_code": ctx.local_code_for_card(card),
        "responsable": ctx.person(card.id_usuario if card else None),
        "fecha_inventario": card.hoj_fec.isoformat() if card and card.hoj_fec else None,
        "anio_inventario": year_from_date(card.hoj_fec) if card else None,
    }


def _margesi_snapshot(db: Session, row: m.InvMargesiItem) -> dict[str, Any]:
    ctx = _build_match_ctx(db, row.tenant_id, [], [row])
    return _margesi_snapshot_ctx(row, ctx)


def _bien_snapshot(db: Session, row: m.InvItemCard, card: m.InvCard | None) -> dict[str, Any]:
    ctx = _build_match_ctx(db, row.tenant_id, [row], [])
    if card:
        ctx.cards[int(card.id)] = card
    return _bien_snapshot_ctx(row, card or ctx.cards.get(int(row.id_card)), ctx)


def _candidatos_bien_clause():
    return and_(
        m.InvItemCard.id_margesi.is_(None),
        or_(
            m.InvItemCard.inv_sit.is_(None),
            m.InvItemCard.inv_sit == "S",
            m.InvItemCard.inv_sit == "C",
        ),
        or_(m.InvItemCard.inv_sit.is_(None), m.InvItemCard.inv_sit != "N"),
    )


def _count_faltantes(db: Session, tenant_id: UUID) -> int:
    linked = (
        select(m.InvItemCard.id_margesi)
        .where(
            m.InvItemCard.tenant_id == tenant_id,
            m.InvItemCard.id_margesi.is_not(None),
        )
        .distinct()
    )
    stmt = (
        select(func.count())
        .select_from(m.InvMargesiItem)
        .where(
            m.InvMargesiItem.tenant_id == tenant_id,
            _margesi_faltantes_inv_sit_clause(),
            m.InvMargesiItem.id.notin_(linked),
            or_(m.InvMargesiItem.inv_sit.is_(None), m.InvMargesiItem.inv_sit != "N"),
        )
    )
    return int(db.scalar(stmt) or 0)


def _count_bienes_candidatos(db: Session, tenant_id: UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(m.InvItemCard)
        .where(m.InvItemCard.tenant_id == tenant_id, _candidatos_bien_clause())
    )
    return int(db.scalar(stmt) or 0)


def _count_flag_inconsistencies(db: Session, tenant_id: UUID) -> int:
    faltante = _margesi_faltantes_inv_sit_clause()
    stmt = (
        select(func.count())
        .select_from(m.InvMargesiItem)
        .join(m.InvItemCard, m.InvItemCard.id_margesi == m.InvMargesiItem.id)
        .where(
            m.InvMargesiItem.tenant_id == tenant_id,
            m.InvItemCard.tenant_id == tenant_id,
            faltante,
        )
    )
    return int(db.scalar(stmt) or 0)


def _count_bien_conciliado_sin_margesi(db: Session, tenant_id: UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(m.InvItemCard)
        .where(
            m.InvItemCard.tenant_id == tenant_id,
            m.InvItemCard.inv_sit == "C",
            m.InvItemCard.id_margesi.is_(None),
        )
    )
    return int(db.scalar(stmt) or 0)


def list_flag_inconsistencies(db: Session, tenant_id: UUID, *, limit: int = 200) -> list[dict[str, Any]]:
    """Caso A: Margesi aparece faltante pero ya tiene bien con id_margesi apuntando a él."""
    faltante = _margesi_faltantes_inv_sit_clause()
    stmt = (
        select(m.InvMargesiItem, m.InvItemCard)
        .join(m.InvItemCard, m.InvItemCard.id_margesi == m.InvMargesiItem.id)
        .where(
            m.InvMargesiItem.tenant_id == tenant_id,
            m.InvItemCard.tenant_id == tenant_id,
            faltante,
        )
        .order_by(m.InvMargesiItem.id.asc())
        .limit(limit)
    )
    out: list[dict[str, Any]] = []
    for marg, bien in db.execute(stmt).all():
        card = db.get(m.InvCard, bien.id_card)
        out.append(
            {
                "kind": "flag_pendiente",
                "title": "Conciliación pendiente por actualización de flag",
                "message": (
                    "El Margesi figura como faltante/no conciliado, pero ya tiene un bien "
                    "inventariado asociado (id_margesi). No es una nueva pareja: solo falta "
                    "actualizar el flag del Margesi."
                ),
                "margesi": _margesi_snapshot(db, marg),
                "bien": _bien_snapshot(db, bien, card),
            }
        )
    return out


def list_bien_conciliado_sin_margesi(
    db: Session, tenant_id: UUID, *, limit: int = 200
) -> list[dict[str, Any]]:
    """Caso B: bien con inv_sit=C pero id_margesi IS NULL."""
    stmt = (
        select(m.InvItemCard)
        .where(
            m.InvItemCard.tenant_id == tenant_id,
            m.InvItemCard.inv_sit == "C",
            m.InvItemCard.id_margesi.is_(None),
        )
        .order_by(m.InvItemCard.id.asc())
        .limit(limit)
    )
    out: list[dict[str, Any]] = []
    for bien in db.scalars(stmt).all():
        card = db.get(m.InvCard, bien.id_card)
        out.append(
            {
                "kind": "bien_sin_margesi",
                "title": "Bien marcado como conciliado sin Margesi asociado",
                "message": (
                    "El bien tiene situación conciliada (C) pero no tiene id_margesi. "
                    "Debe buscarse un faltante Margesi candidato."
                ),
                "bien": _bien_snapshot(db, bien, card),
                "margesi": None,
            }
        )
    return out


def _load_faltantes(
    db: Session, tenant_id: UUID, *, limit: int = FALTANTES_MATCH_LIMIT
) -> list[m.InvMargesiItem]:
    linked = (
        select(m.InvItemCard.id_margesi)
        .where(
            m.InvItemCard.tenant_id == tenant_id,
            m.InvItemCard.id_margesi.is_not(None),
        )
        .distinct()
    )
    stmt = (
        select(m.InvMargesiItem)
        .options(
            load_only(
                m.InvMargesiItem.id,
                m.InvMargesiItem.tenant_id,
                m.InvMargesiItem.mar_num,
                m.InvMargesiItem.mar_cpat,
                m.InvMargesiItem.mar_des,
                m.InvMargesiItem.mar_mar,
                m.InvMargesiItem.mar_mod,
                m.InvMargesiItem.mar_ser,
                m.InvMargesiItem.mar_est,
                m.InvMargesiItem.amb_cod,
                m.InvMargesiItem.usuario_libre,
                m.InvMargesiItem.usu_cod,
                m.InvMargesiItem.usu_resp_cod,
                m.InvMargesiItem.inv_sit,
                m.InvMargesiItem.inv_num,
                m.InvMargesiItem.inv_con,
                m.InvMargesiItem.mar_ing_fdadq,
                m.InvMargesiItem.extra,
            )
        )
        .where(
            m.InvMargesiItem.tenant_id == tenant_id,
            _margesi_faltantes_inv_sit_clause(),
            m.InvMargesiItem.id.notin_(linked),
            or_(m.InvMargesiItem.inv_sit.is_(None), m.InvMargesiItem.inv_sit != "N"),
        )
        .order_by(m.InvMargesiItem.id.asc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def _load_bienes_for_sbn_keys(
    db: Session,
    tenant_id: UUID,
    sbn_keys: set[str],
    *,
    limit: int = BIENES_MATCH_LIMIT,
) -> list[m.InvItemCard]:
    """Carga solo bienes candidatos cuyo SBN coincide con faltantes (blocking SQL)."""
    keys = sorted(k for k in sbn_keys if k)
    if not keys:
        return []

    stmt = (
        select(m.InvItemCard)
        .options(
            load_only(
                m.InvItemCard.id,
                m.InvItemCard.tenant_id,
                m.InvItemCard.id_card,
                m.InvItemCard.inv_num,
                m.InvItemCard.mar_cpat,
                m.InvItemCard.mar_des,
                m.InvItemCard.inv_sit,
                m.InvItemCard.id_margesi,
                m.InvItemCard.extra,
            )
        )
        .where(m.InvItemCard.tenant_id == tenant_id, _candidatos_bien_clause())
    )
    prefixes = [k[:8] for k in keys if len(k) >= 8]
    short = [k for k in keys if 0 < len(k) < 8]
    like_parts = []
    for p in prefixes[:400]:
        like_parts.append(m.InvItemCard.mar_cpat.ilike(f"%{p}%"))
    for p in short[:100]:
        like_parts.append(m.InvItemCard.mar_cpat.ilike(f"%{p}%"))
    if not like_parts:
        return []
    stmt = stmt.where(or_(*like_parts)).order_by(m.InvItemCard.id.asc()).limit(limit)
    return list(db.scalars(stmt).all())


def _load_bienes_sin_sbn_pool(
    db: Session, tenant_id: UUID, *, limit: int = 3000
) -> list[m.InvItemCard]:
    stmt = (
        select(m.InvItemCard)
        .where(
            m.InvItemCard.tenant_id == tenant_id,
            _candidatos_bien_clause(),
            or_(m.InvItemCard.mar_cpat.is_(None), func.trim(m.InvItemCard.mar_cpat) == ""),
        )
        .order_by(m.InvItemCard.id.asc())
        .limit(limit)
    )
    return list(db.scalars(stmt).all())


def build_match_proposals(
    db: Session,
    tenant_id: UUID,
    *,
    local_code: str | None = None,
    sbn: str | None = None,
    tier: str | None = None,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Genera propuestas con blocking por SBN y caches (sin N+1)."""
    faltantes = _load_faltantes(db, tenant_id)
    sbn_filter = normalize_sbn(sbn)
    if sbn_filter:
        faltantes = [
            f
            for f in faltantes
            if (ms := normalize_sbn(f.mar_cpat))
            and (ms.startswith(sbn_filter) or sbn_filter.startswith(ms[:8]))
        ]

    sbn_keys = {normalize_sbn(f.mar_cpat) for f in faltantes if normalize_sbn(f.mar_cpat)}
    bienes = _load_bienes_for_sbn_keys(db, tenant_id, sbn_keys)
    needs_serie_pool = any(
        not normalize_sbn(f.mar_cpat) and (f.mar_ser or "").strip() for f in faltantes
    )
    bienes_sin_sbn: list[m.InvItemCard] = []
    if needs_serie_pool:
        bienes_sin_sbn = _load_bienes_sin_sbn_pool(db, tenant_id)

    ctx = _build_match_ctx(db, tenant_id, bienes + bienes_sin_sbn, faltantes)

    by_sbn: dict[str, list[m.InvItemCard]] = defaultdict(list)
    for b in bienes:
        key = normalize_sbn(b.mar_cpat)
        if len(key) >= 8:
            by_sbn[key[:8]].append(b)
        elif key:
            by_sbn[key].append(b)

    serie_index: dict[str, list[m.InvItemCard]] = defaultdict(list)
    for b in bienes_sin_sbn:
        nser = normalize_serie(_bien_field(b, "mar_ser"))
        if nser:
            serie_index[nser].append(b)

    local_filter = (local_code or "").strip().upper()
    search_q = (search or "").strip().lower()

    scored: list[tuple[float, str, int, int, list, m.InvMargesiItem, m.InvItemCard]] = []
    used_bienes: set[int] = set()

    for marg in faltantes:
        ms = normalize_sbn(marg.mar_cpat)
        candidates: list[m.InvItemCard] = []
        if len(ms) >= 8:
            candidates = list(by_sbn.get(ms[:8], []))
        elif ms:
            candidates = list(by_sbn.get(ms, []))
        else:
            nser = normalize_serie(marg.mar_ser)
            if not nser:
                continue
            candidates = list(serie_index.get(nser, []))

        marg_local_code = str(marg.amb_cod or "").strip().upper()
        local_m = ctx.local_label_for_margesi(marg)
        resp_m = str(marg.usuario_libre or marg.usu_cod or "").strip()
        year_m = year_from_date(marg.mar_ing_fdadq)

        best: tuple[float, str, list, m.InvItemCard] | None = None

        for bien in candidates:
            bid = int(bien.id)
            if bid in used_bienes:
                continue
            card = ctx.cards.get(int(bien.id_card))
            bien_local_code = ctx.local_code_for_card(card).upper()
            if local_filter and bien_local_code != local_filter and marg_local_code != local_filter:
                continue

            score, evidences, blocked = score_pair(
                sbn_m=marg.mar_cpat,
                sbn_b=bien.mar_cpat,
                serie_m=marg.mar_ser,
                serie_b=_bien_field(bien, "mar_ser"),
                marca_m=marg.mar_mar,
                marca_b=_bien_field(bien, "mar_mar"),
                modelo_m=marg.mar_mod,
                modelo_b=_bien_field(bien, "mar_mod"),
                local_m=local_m,
                local_b=ctx.local_label_for_card(card),
                resp_m=resp_m,
                resp_b=ctx.person(card.id_usuario if card else None),
                estado_m=marg.mar_est,
                estado_b=_bien_field(bien, "mar_est") or "B",
                year_m=year_m,
                year_b=year_from_date(card.hoj_fec) if card else None,
            )
            if blocked or score < 20:
                continue
            tier_name = classify_tier(score)
            if best is None or score > best[0]:
                best = (score, tier_name, evidences, bien)

        if best is not None:
            score, tier_name, evidences, bien = best
            scored.append((score, tier_name, int(marg.id), int(bien.id), evidences, marg, bien))
            used_bienes.add(int(bien.id))

    if search_q:
        filtered = []
        for item in scored:
            _, _, _, _, _, marg, bien = item
            blob = " ".join(
                [
                    str(_margesi_codigo_interno(marg) or ""),
                    str(marg.mar_cpat or ""),
                    str(marg.mar_ser or ""),
                    str(format_inv_num(bien.inv_num) if bien.inv_num is not None else ""),
                    str(bien.mar_cpat or ""),
                    str(_bien_field(bien, "mar_ser")),
                    str(marg.mar_mod or ""),
                    str(_bien_field(bien, "mar_mod")),
                ]
            ).lower()
            if search_q in blob:
                filtered.append(item)
        scored = filtered

    scored.sort(key=lambda x: (-x[0], x[2]))

    counts = {
        "faltantes": _count_faltantes(db, tenant_id),
        "bienes_candidatos": _count_bienes_candidatos(db, tenant_id),
        "fuerte": sum(1 for s in scored if s[1] == "fuerte"),
        "probable": sum(1 for s in scored if s[1] == "probable"),
        "revisar": sum(1 for s in scored if s[1] == "revisar"),
        "propuestas_total": len(scored),
        "faltantes_evaluados": len(faltantes),
    }

    if tier in ("fuerte", "probable", "revisar"):
        scored = [s for s in scored if s[1] == tier]
        counts["propuestas_total"] = len(scored)

    page_items = scored[offset : offset + limit]
    page: list[dict[str, Any]] = []
    for score, tier_name, marg_id, bien_id, evidences, marg, bien in page_items:
        card = ctx.cards.get(int(bien.id_card))
        prop = MatchProposal(
            margesi_id=marg_id,
            itemcard_id=bien_id,
            score=score,
            tier=tier_name,
            evidences=evidences,
            margesi=_margesi_snapshot_ctx(marg, ctx),
            bien=_bien_snapshot_ctx(bien, card, ctx),
        )
        page.append(prop.to_dict())

    return page, counts


def summary(db: Session, tenant_id: UUID) -> dict[str, Any]:
    """Resumen rápido con COUNT (sin motor de coincidencias)."""
    flags = _count_flag_inconsistencies(db, tenant_id)
    sin_marg = _count_bien_conciliado_sin_margesi(db, tenant_id)
    return {
        "faltantes_no_conciliados": _count_faltantes(db, tenant_id),
        "sobrantes_candidatos": _count_bienes_candidatos(db, tenant_id),
        "coincidencias_fuertes": 0,
        "coincidencias_probables": 0,
        "coincidencias_revisar": 0,
        "inconsistencias_directas": flags + sin_marg,
        "inconsistencias_flag": flags,
        "inconsistencias_bien_sin_margesi": sin_marg,
        "matches_pending": True,
    }


def fix_flag_inconsistency(
    db: Session,
    tenant_id: UUID,
    margesi_id: int,
    *,
    user_id: UUID | None = None,
) -> tuple[bool, str]:
    """Actualiza flag del Margesi a conciliado cuando ya hay bien asociado."""
    marg = db.get(m.InvMargesiItem, margesi_id)
    if not marg or marg.tenant_id != tenant_id:
        return False, "Margesi no encontrado"
    bien = db.scalar(
        select(m.InvItemCard).where(
            m.InvItemCard.tenant_id == tenant_id,
            m.InvItemCard.id_margesi == margesi_id,
        )
    )
    if not bien:
        return False, "No hay bien asociado a este Margesi"
    before = {"inv_sit": marg.inv_sit, "inv_num": marg.inv_num, "inv_con": marg.inv_con}
    marg_inv_sit_before = marg.inv_sit
    bien_inv_sit_before = bien.inv_sit
    marg.inv_sit = "C"
    marg.inv_con = "1"
    marg.inv_num = format_inv_num(bien.inv_num)
    if bien.inv_sit != "C":
        bien.inv_sit = "C"
        bien.inv_con = "1"
    db.add(marg)
    db.add(bien)
    _write_audit(
        db,
        tenant_id,
        user_id=user_id,
        bien=bien,
        action="conciliar",
        note=f"Fix flag Margesi {margesi_id}: {before} → C/inv_num={marg.inv_num}",
    )
    db.commit()
    _schedule_inventory_caches_refresh(
        db,
        tenant_id,
        marg=marg,
        bien=bien,
        marg_inv_sit_before=marg_inv_sit_before,
        bien_inv_sit_before=bien_inv_sit_before,
    )
    return True, "Flag del Margesi actualizado a conciliado"


def confirm_proposal(
    db: Session,
    tenant_id: UUID,
    margesi_id: int,
    itemcard_id: int,
    *,
    user_id: UUID | None = None,
    observacion: str | None = None,
    evidencias: list[dict[str, Any]] | None = None,
) -> tuple[bool, str]:
    """Confirma manualmente una propuesta (nunca automática)."""
    marg = db.get(m.InvMargesiItem, margesi_id)
    bien = db.get(m.InvItemCard, itemcard_id)
    if not marg or marg.tenant_id != tenant_id:
        return False, "Margesi no encontrado"
    if not bien or bien.tenant_id != tenant_id:
        return False, "Bien no encontrado"
    if bien.id_margesi and int(bien.id_margesi) != int(marg.id):
        return False, "El bien ya está asociado a otro Margesi"
    if bien.id_margesi == marg.id and marg.inv_sit == "C":
        return False, "Ya están conciliados"
    other = db.scalar(
        select(m.InvItemCard.id).where(
            m.InvItemCard.tenant_id == tenant_id,
            m.InvItemCard.id_margesi == marg.id,
            m.InvItemCard.id != bien.id,
        )
    )
    if other:
        return False, "El Margesi ya está asociado a otro bien"

    if marg.inv_sit == "N" or bien.inv_sit == "N":
        return False, "No se puede conciliar un registro marcado como no conciliable"

    if bien.inv_sit not in (None, "S", "C"):
        return False, f"Situación del bien no apta para conciliar ({bien.inv_sit})"

    marg_before = {"inv_sit": marg.inv_sit, "inv_num": marg.inv_num, "id": marg.id}
    bien_before = {"inv_sit": bien.inv_sit, "id_margesi": bien.id_margesi, "id": bien.id}
    marg_inv_sit_before = marg.inv_sit
    bien_inv_sit_before = bien.inv_sit

    mar_num = _margesi_codigo_interno(marg)
    extra = dict(bien.extra or {})
    if mar_num:
        extra["mar_npri"] = mar_num
    if observacion:
        extra["mar_obs"] = observacion.strip()

    card = db.get(m.InvCard, bien.id_card)
    marg.inv_num = format_inv_num(bien.inv_num)
    marg.inv_sit = "C"
    marg.inv_con = "1"
    if card and card.hoj_num is not None:
        marg.inv_hoj = format_inv_num(card.hoj_num)

    bien.mar_num = mar_num
    bien.inv_sit = "C"
    bien.inv_con = "1"
    bien.id_margesi = marg.id
    bien.extra = extra or None

    reasons = []
    for ev in evidencias or []:
        if ev.get("status") in ("match", "partial"):
            reasons.append(str(ev.get("label") or ev.get("key") or ""))
    note = (
        f"Conciliación Margesi confirmada. Margesi={margesi_id} Bien={itemcard_id}. "
        f"Motivos: {', '.join(reasons) or 'revisión manual'}. "
        f"Antes margesi={marg_before} bien={bien_before}"
    )
    db.add(marg)
    db.add(bien)
    _write_audit(db, tenant_id, user_id=user_id, bien=bien, action="conciliar", note=note[:500])
    db.commit()
    _schedule_inventory_caches_refresh(
        db,
        tenant_id,
        marg=marg,
        bien=bien,
        marg_inv_sit_before=marg_inv_sit_before,
        bien_inv_sit_before=bien_inv_sit_before,
    )
    return True, "Conciliación confirmada"


def _write_audit(
    db: Session,
    tenant_id: UUID,
    *,
    user_id: UUID | None,
    bien: m.InvItemCard,
    action: str,
    note: str,
) -> None:
    db.add(
        m.InvItemAuditLog(
            tenant_id=tenant_id,
            user_id=user_id,
            action=action[:20],
            itemcard_id=int(bien.id),
            card_id=int(bien.id_card),
            inv_num=format_inv_num(bien.inv_num) if bien.inv_num is not None else None,
            mar_des=(note or bien.mar_des or "")[:500],
            created_at=datetime.now(timezone.utc),
        )
    )
