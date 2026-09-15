"""Servicios del API móvil: catálogo offline, lookup, IA heurística y sync por lotes."""

from __future__ import annotations

import base64
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.inventory_numbers import format_hoj_num, format_inv_num, try_parse_inventory_number
from app.modules.iam.models import User
from app.modules.inventory import attendance_service as att
from app.modules.inventory import models as m
from app.modules.inventory import service as inv
from app.modules.inventory.mobile_schemas import (
    MobileEnsureCardRequest,
    MobileIdentifyRequest,
    MobileSyncItem,
    MobileSyncRequest,
)
from app.modules.inventory.schemas import CardItemWrite, CardWrite

logger = logging.getLogger(__name__)
LIMA_TZ = ZoneInfo("America/Lima")

_SCAN_TIPOS = ("M", "S", "A", "R", "SE")

_ESTADO_LABEL = {
    "N": "Nuevo",
    "B": "Bueno",
    "R": "Regular",
    "M": "Malo",
    "I": "Inservible",
}

_IA_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Computadora portátil", ("laptop", "portatil", "notebook", "latitude", "thinkpad", "macbook")),
    ("Computadora de escritorio", ("desktop", "pc ", "cpu", "tower", "all in one", "imac")),
    ("Monitor", ("monitor", "pantalla", "display", "lcd", "led 24", "led 27")),
    ("Impresora", ("impresora", "printer", "multifuncional", "laserjet")),
    ("Escáner", ("escaner", "scanner")),
    ("Proyector", ("proyector", "projector")),
    ("Silla", ("silla", "chair", "sillon")),
    ("Escritorio", ("escritorio", "mesa", "desk")),
    ("Archivador", ("archivador", "archivo metalico", "anaquel")),
    ("Aire acondicionado", ("aire acondicionado", "split", "acondicionado")),
    ("Teléfono", ("telefono", "anexo", "ip phone")),
    ("Vehículo", ("camioneta", "auto", "vehiculo", "motocicleta")),
]


def _today_lima():
    return datetime.now(LIMA_TZ).date()


def _fold(value: str | None) -> str:
    raw = unicodedata.normalize("NFKD", (value or "").lower())
    return "".join(ch for ch in raw if not unicodedata.combining(ch))


def _tokens(value: str | None) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", _fold(value)) if t}


def _estado_label(code: str | None) -> str:
    key = (code or "B").strip().upper()[:1] or "B"
    return _ESTADO_LABEL.get(key, "Bueno")


def _person_label(person: m.InvPerson | None) -> str | None:
    if not person:
        return None
    num = (person.number or "").strip()
    name = (person.name or "").strip()
    if num and name:
        return f"{num} - {name}"
    return name or num or None


def _ambiente_label(env: m.InvEnvironment | None) -> str | None:
    if not env:
        return None
    code = (env.code or "").strip()
    desc = (env.description or "").strip()
    if code and desc:
        return f"{code} - {desc}"
    return desc or code or None


def _local_label(est: m.InvEstablishment | None) -> str | None:
    if not est:
        return None
    code = (est.code or "").strip()
    desc = (est.description or "").strip()
    if code and desc:
        return f"{code} - {desc}"
    return desc or code or None


def _minutes_ago(dt: datetime | None) -> int | None:
    if not dt:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - dt.astimezone(timezone.utc)
    return max(0, int(delta.total_seconds() // 60))


def bootstrap(db: Session, tenant_id: UUID, user: User) -> dict[str, Any]:
    tables = inv.hoja_captura_tables(db, tenant_id, user.id)
    item_tables = inv.item_card_tables(db, tenant_id, user.id)
    cards = _open_cards_for_user(db, tenant_id, user.id)
    items_today = att._count_items_for_user_today(db, tenant_id, user.id)
    establishments = att.list_user_establishments(db, tenant_id, user.id)
    if not establishments:
        establishments = [
            {
                "id": int(e["id"]),
                "code": e.get("code"),
                "description": e.get("description"),
                "address": e.get("address"),
                "latitude": e.get("latitude"),
                "longitude": e.get("longitude"),
                "geofence_radius_m": e.get("geofence_radius_m") or 100,
                "hojas_count": 0,
            }
            for e in tables.get("establishments") or []
        ]
    return {
        "user": {
            "id": str(user.id),
            "full_name": user.full_name,
            "email": user.email,
            **inv.user_inventory_conf(user).model_dump(),
        },
        "work_date": _today_lima().isoformat(),
        "items_inventoried_today": items_today,
        "catalog": {
            "establishments": tables.get("establishments") or [],
            "environments": tables.get("environments") or [],
            "persons": tables.get("persons") or [],
            "cost_centers": tables.get("cost_centers") or [],
            "list_sbn": item_tables.get("list_sbn") or [],
        },
        "assigned_establishments": establishments,
        "open_cards": cards,
        "user_conf": tables.get("user_conf") or {},
    }


def catalog_index(
    db: Session,
    tenant_id: UUID,
    *,
    page: int = 1,
    per_page: int = 400,
    search: str | None = None,
) -> dict[str, Any]:
    stmt = select(m.InvMargesiItem).where(m.InvMargesiItem.tenant_id == tenant_id)
    term = (search or "").strip()
    if term:
        like = f"%{term}%"
        stmt = stmt.where(
            or_(
                m.InvMargesiItem.mar_num.ilike(like),
                m.InvMargesiItem.mar_cpat.ilike(like),
                m.InvMargesiItem.mar_des.ilike(like),
                m.InvMargesiItem.mar_mar.ilike(like),
                m.InvMargesiItem.mar_mod.ilike(like),
                m.InvMargesiItem.inv_num.ilike(like),
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(m.InvMargesiItem.id.asc()).offset((page - 1) * per_page).limit(per_page)
    ).all()
    return {
        "data": [_catalog_row(r) for r in rows],
        "meta": {
            "page": page,
            "per_page": per_page,
            "total": int(total),
            "pages": max(1, (int(total) + per_page - 1) // per_page),
        },
    }


def _catalog_row(row: m.InvMargesiItem) -> dict[str, Any]:
    extra = row.extra if isinstance(row.extra, dict) else {}
    return {
        "id": int(row.id),
        "mar_num": row.mar_num,
        "mar_cpat": row.mar_cpat,
        "inv_num": row.inv_num,
        "inv_num_1": str(row.inv_num_1) if row.inv_num_1 is not None else None,
        "inv_num_2": str(row.inv_num_2) if row.inv_num_2 is not None else None,
        "mar_des": row.mar_des,
        "mar_mar": row.mar_mar or extra.get("mar_mar"),
        "mar_mod": row.mar_mod or extra.get("mar_mod"),
        "mar_ser": row.mar_ser or extra.get("mar_ser"),
        "mar_est": row.mar_est,
        "amb_cod": row.amb_cod,
        "local": row.local_libre,
        "ambiente": row.ambiente_libre,
        "usuario": row.usuario_libre,
        "inv_sit": row.inv_sit,
        "inventariado": bool(row.inv_num and str(row.inv_num).strip()),
    }


def lookup_code(
    db: Session,
    tenant_id: UUID,
    user: User,
    valor: str,
    tipo: str | None = None,
    current_environment_id: int | None = None,
) -> dict[str, Any]:
    raw = (valor or "").strip()
    if not raw:
        return {"success": False, "message": "Código vacío", "esta_conciliado": False}

    tipos = [tipo.strip().upper()] if tipo else list(_SCAN_TIPOS)
    found: dict[str, Any] | None = None
    used_tipo = None
    for t in tipos:
        data = inv.record_margesi_cod(db, tenant_id, raw, t, user.id)
        if data.get("success"):
            found = data
            used_tipo = t
            break

    if not found:
        matches = identify(
            db,
            tenant_id,
            MobileIdentifyRequest(scanned_code=raw, ocr_text=raw, environment_id=current_environment_id),
        )
        return {
            "success": False,
            "message": "Bien no se encuentra. Se sugieren coincidencias.",
            "esta_conciliado": False,
            "scanned_code": raw,
            "scan_tipo": used_tipo,
            "candidates": matches.get("candidates") or [],
            "ai": matches.get("ai"),
        }

    item = found.get("item") or {}
    card_info = found.get("card_info") or {}
    current_env = db.get(m.InvEnvironment, current_environment_id) if current_environment_id else None
    current_est = (
        db.get(m.InvEstablishment, current_env.establishment_id)
        if current_env and current_env.establishment_id
        else None
    )
    registered_env = (card_info.get("ambiente") or item.get("ambiente_libre") or item.get("amb_cod") or "").strip()
    current_label = _ambiente_label(current_env)
    location_mismatch = bool(
        current_label
        and registered_env
        and _fold(registered_env) not in _fold(current_label)
        and _fold(current_label) not in _fold(registered_env)
    )

    duplicate = _duplicate_for_code(db, tenant_id, raw, item.get("id") or found.get("id_margesi"))
    return {
        **found,
        "scanned_code": raw,
        "scan_tipo": used_tipo,
        "estado_sugerido": _estado_label(item.get("mar_est")),
        "responsable": card_info.get("usuario") or item.get("usuario_libre"),
        "ubicacion_registrada": registered_env or card_info.get("local"),
        "ubicacion_actual": current_label,
        "local_actual": _local_label(current_est),
        "location_mismatch": location_mismatch,
        "duplicate": duplicate,
    }


def _duplicate_for_code(
    db: Session, tenant_id: UUID, code: str, id_margesi: int | None
) -> dict[str, Any] | None:
    stmt = (
        select(m.InvItemCard, m.InvCard, User)
        .join(m.InvCard, m.InvCard.id == m.InvItemCard.id_card)
        .outerjoin(User, User.id == m.InvCard.id_inventariador)
        .where(m.InvItemCard.tenant_id == tenant_id)
    )
    if id_margesi:
        stmt = stmt.where(m.InvItemCard.id_margesi == id_margesi)
    else:
        like = code.strip()
        stmt = stmt.where(
            or_(
                m.InvItemCard.mar_num == like,
                m.InvItemCard.inv_num_1 == like,
                m.InvItemCard.inv_num_2 == like,
                m.InvItemCard.mar_cpat == like,
            )
        )
    row = db.execute(stmt.order_by(m.InvItemCard.created_at.desc()).limit(1)).first()
    if not row:
        return None
    item, card, inventariador = row
    minutes = _minutes_ago(item.created_at)
    name = inventariador.full_name if inventariador else "otra brigada"
    return {
        "item_id": int(item.id),
        "card_id": int(card.id) if card else None,
        "hoj_num": format_hoj_num(card.hoj_num) if card and card.hoj_num is not None else None,
        "inv_num": format_inv_num(item.inv_num) if item.inv_num is not None else None,
        "inventariador": name,
        "minutes_ago": minutes,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "message": f"Este bien ya fue inventariado hace {minutes} minutos por {name}."
        if minutes is not None
        else f"Este bien ya fue inventariado por {name}.",
    }


def identify(db: Session, tenant_id: UUID, body: MobileIdentifyRequest) -> dict[str, Any]:
    haystack = " ".join(
        filter(
            None,
            [body.ocr_text, body.description, body.marca, body.modelo, body.scanned_code, *body.labels],
        )
    )
    ai_label, ai_conf = _classify_asset(haystack)
    query_tokens = _tokens(haystack)
    if body.marca:
        query_tokens |= _tokens(body.marca)
    if body.modelo:
        query_tokens |= _tokens(body.modelo)

    env = db.get(m.InvEnvironment, body.environment_id) if body.environment_id else None
    env_code = (env.code or "").strip() if env else ""
    env_desc = (env.description or "").strip() if env else ""

    stmt = select(m.InvMargesiItem).where(m.InvMargesiItem.tenant_id == tenant_id)
    code = (body.scanned_code or "").strip()
    filters = []
    if code:
        like = f"%{code}%"
        filters.append(
            or_(
                m.InvMargesiItem.mar_num.ilike(like),
                m.InvMargesiItem.mar_cpat.ilike(like),
                m.InvMargesiItem.inv_num.ilike(like),
                m.InvMargesiItem.mar_des.ilike(like),
            )
        )
    if body.marca:
        filters.append(m.InvMargesiItem.mar_mar.ilike(f"%{body.marca.strip()}%"))
    if body.modelo:
        filters.append(m.InvMargesiItem.mar_mod.ilike(f"%{body.modelo.strip()}%"))
    if body.description:
        filters.append(m.InvMargesiItem.mar_des.ilike(f"%{body.description.strip()[:80]}%"))
    if env_code:
        filters.append(
            or_(
                m.InvMargesiItem.amb_cod == env_code,
                m.InvMargesiItem.ambiente_libre.ilike(f"%{env_desc or env_code}%"),
            )
        )
    if filters:
        stmt = stmt.where(or_(*filters))
    rows = db.scalars(stmt.order_by(m.InvMargesiItem.id.desc()).limit(80)).all()

    scored: list[tuple[float, m.InvMargesiItem]] = []
    for row in rows:
        score = _match_score(row, query_tokens, code, body, env_code, env_desc, ai_label)
        if score >= 18:
            scored.append((score, row))
    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = []
    for score, row in scored[: body.limit]:
        candidates.append(
            {
                **_catalog_row(row),
                "confidence": min(99.0, round(score, 1)),
                "reason": _match_reason(row, code, body, env_code),
            }
        )
    return {
        "ai": {
            "label": ai_label,
            "confidence": ai_conf,
            "probable_sbn": candidates[0]["mar_cpat"] if candidates else None,
            "marca": (body.marca or (candidates[0].get("mar_mar") if candidates else None)),
        },
        "candidates": candidates,
    }


def _classify_asset(text: str) -> tuple[str, float]:
    folded = _fold(text)
    if not folded.strip():
        return "Bien patrimonial", 40.0
    for label, keys in _IA_KEYWORDS:
        if any(k in folded for k in keys):
            return label, 92.0 if label.startswith("Computadora") else 86.0
    return "Bien patrimonial", 48.0


def _match_score(
    row: m.InvMargesiItem,
    query_tokens: set[str],
    code: str,
    body: MobileIdentifyRequest,
    env_code: str,
    env_desc: str,
    ai_label: str,
) -> float:
    score = 0.0
    extra = row.extra if isinstance(row.extra, dict) else {}
    codes = [
        str(row.mar_num or ""),
        str(row.mar_cpat or ""),
        str(row.inv_num or ""),
        str(row.inv_num_1 or ""),
        str(row.inv_num_2 or ""),
    ]
    if code and any(code.lower() == c.lower() for c in codes if c):
        score += 70
    elif code and any(code.lower() in c.lower() for c in codes if c):
        score += 40
    row_tokens = _tokens(" ".join([row.mar_des or "", row.mar_mar or "", row.mar_mod or "", extra.get("mar_mar") or ""]))
    if query_tokens and row_tokens:
        overlap = query_tokens & row_tokens
        score += min(30, len(overlap) * 6)
    if body.marca and _fold(body.marca) in _fold(row.mar_mar or extra.get("mar_mar") or ""):
        score += 18
    if body.modelo and _fold(body.modelo) in _fold(row.mar_mod or extra.get("mar_mod") or ""):
        score += 14
    if env_code and (row.amb_cod or "") == env_code:
        score += 12
    elif env_desc and _fold(env_desc) in _fold(row.ambiente_libre or ""):
        score += 8
    if ai_label != "Bien patrimonial" and _fold(ai_label.split()[0]) in _fold(row.mar_des or ""):
        score += 8
    if row.inv_num and str(row.inv_num).strip():
        score -= 6
    return score


def _match_reason(row: m.InvMargesiItem, code: str, body: MobileIdentifyRequest, env_code: str) -> str:
    bits = []
    if code and code in (row.mar_num or ""):
        bits.append("código exacto")
    if body.marca and row.mar_mar:
        bits.append("marca")
    if body.modelo and row.mar_mod:
        bits.append("modelo")
    if env_code and row.amb_cod == env_code:
        bits.append("misma ubicación")
    if row.mar_des:
        bits.append("descripción")
    return ", ".join(bits) or "similitud general"


def ensure_open_card(
    db: Session, tenant_id: UUID, user: User, body: MobileEnsureCardRequest
) -> dict[str, Any]:
    existing = _open_card_for_ambiente(db, tenant_id, user.id, body.id_ambiente)
    if existing:
        return {"created": False, "card": existing}

    env = db.get(m.InvEnvironment, body.id_ambiente)
    if not env or env.tenant_id != tenant_id:
        raise ValueError("Ambiente no encontrado")
    cc = db.get(m.InvCostCenter, body.id_ccosto)
    if not cc or cc.tenant_id != tenant_id:
        raise ValueError("Centro de costo no encontrado")

    hoj_num = _next_hoj_num(db, tenant_id, user)
    card = inv.upsert_card(
        db,
        tenant_id,
        CardWrite(
            hoj_num=hoj_num,
            hoj_fec=_today_lima(),
            id_ambiente=body.id_ambiente,
            id_ccosto=body.id_ccosto,
            id_usuario=body.id_usuario,
            id_inventariador=user.id,
            id_digitador=user.id,
            nota_interna=body.nota_interna or "Hoja creada desde app móvil",
            state=1,
        ),
        user.id,
        hoja_captura_mode=True,
    )
    db.refresh(card)
    return {"created": True, "card": _card_payload(db, card)}


def sync_batch(db: Session, tenant_id: UUID, user: User, body: MobileSyncRequest) -> dict[str, Any]:
    results = []
    ok = 0
    for item in body.items:
        try:
            results.append(_sync_one(db, tenant_id, user, item))
            if results[-1].get("success"):
                ok += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error sincronizando ítem móvil %s", item.client_id)
            results.append(
                {
                    "client_id": item.client_id,
                    "success": False,
                    "message": str(exc),
                }
            )
    return {"success": ok == len(body.items), "synced": ok, "total": len(body.items), "results": results}


def _sync_one(db: Session, tenant_id: UUID, user: User, item: MobileSyncItem) -> dict[str, Any]:
    card_id = item.card_id
    if not card_id:
        if not item.id_ambiente or not item.id_ccosto:
            return {"client_id": item.client_id, "success": False, "message": "Falta hoja o ambiente/centro de costo"}
        ensured = ensure_open_card(
            db,
            tenant_id,
            user,
            MobileEnsureCardRequest(
                id_ambiente=item.id_ambiente,
                id_ccosto=item.id_ccosto,
                id_usuario=item.id_usuario,
            ),
        )
        card_id = int(ensured["card"]["id"])

    card = db.get(m.InvCard, card_id)
    if not card or card.tenant_id != tenant_id:
        return {"client_id": item.client_id, "success": False, "message": "Hoja no encontrada"}

    inv_num = item.inv_num
    if inv_num in (None, ""):
        inv_num = user.eti_act or user.num_act
    if inv_num in (None, ""):
        return {"client_id": item.client_id, "success": False, "message": "Número de inventario no disponible"}

    marg = None
    if item.id_margesi:
        marg = db.get(m.InvMargesiItem, item.id_margesi)
        if marg and marg.tenant_id != tenant_id:
            marg = None
    extra_marg = marg.extra if marg and isinstance(marg.extra, dict) else {}

    def _pick(*values: object, fallback: str = "S/D") -> str:
        for value in values:
            if value is not None and str(value).strip():
                return str(value).strip()
        return fallback

    photo_urls: dict[str, str] = {}
    for photo in item.photos[:3]:
        try:
            raw = base64.b64decode(photo.content_base64)
        except Exception:
            continue
        if not raw:
            continue
        url = inv.save_hoja_captura_item_photo(tenant_id, inv_num, photo.slot, raw, photo.filename)
        key = {1: "mar_foto", 2: "mar_foto2", 3: "mar_foto3"}.get(photo.slot, "mar_foto")
        photo_urls[key] = url

    write = CardItemWrite(
        id_margesi=item.id_margesi if marg else None,
        no_conciliar=item.no_conciliar or not marg,
        inv_num=inv_num,
        inv_num_1=item.inv_num_1 or item.scanned_code,
        inv_num_2=item.inv_num_2,
        mar_num=item.mar_num or item.scanned_code or (marg.mar_num if marg else None),
        mar_cpat=item.mar_cpat or (marg.mar_cpat if marg else None),
        mar_des=_pick(item.mar_des, marg.mar_des if marg else None, fallback="Bien inventariado (app)"),
        mar_mar=_pick(item.mar_mar, marg.mar_mar if marg else None, extra_marg.get("mar_mar")),
        mar_mod=_pick(item.mar_mod, marg.mar_mod if marg else None, extra_marg.get("mar_mod")),
        mar_ser=_pick(item.mar_ser, marg.mar_ser if marg else None, extra_marg.get("mar_ser")),
        mar_col=_pick(item.mar_col, extra_marg.get("mar_col"), marg.mar_col if marg else None),
        mar_med=_pick(item.mar_med, extra_marg.get("mar_med"), marg.mar_med if marg else None),
        mar_esp=item.mar_esp,
        mar_uso=item.mar_uso,
        mar_seg=item.mar_seg or "S",
        mar_tip=item.mar_tip,
        mar_ano=item.mar_ano,
        mar_npla=item.mar_npla,
        mar_nmot=item.mar_nmot,
        mar_ncha=item.mar_ncha,
        mar_eti=item.mar_eti,
        mar_npri=item.mar_npri,
        mar_ccat=item.mar_ccat,
        mar_est=item.mar_est or (marg.mar_est if marg else None) or "B",
        mar_obs=item.mar_obs,
        mar_foto=photo_urls.get("mar_foto") or item.mar_foto,
        mar_foto2=photo_urls.get("mar_foto2") or item.mar_foto2,
        mar_foto3=photo_urls.get("mar_foto3") or item.mar_foto3,
    )
    success, message = inv.store_card_item(db, tenant_id, card_id, write, operator_id=user.id)
    if not success:
        return {"client_id": item.client_id, "success": False, "message": message, "card_id": card_id}

    parsed_inv = try_parse_inventory_number(inv_num)
    saved = None
    if parsed_inv is not None:
        saved = db.scalar(
            select(m.InvItemCard).where(
                m.InvItemCard.tenant_id == tenant_id,
                m.InvItemCard.id_card == card_id,
                m.InvItemCard.inv_num == parsed_inv,
            )
        )
    if saved:
        extra = dict(saved.extra or {})
        extra.update(
            {
                k: v
                for k, v in {
                    "mobile_lat": item.latitude,
                    "mobile_lng": item.longitude,
                    "mobile_accuracy_m": item.accuracy_m,
                    "scanned_code": item.scanned_code,
                    "scan_tipo": item.scan_tipo,
                    "captured_at": item.captured_at,
                    "ai_label": item.ai_label,
                    "ai_confidence": item.ai_confidence,
                    "source": "sgip_brigadas",
                }.items()
                if v is not None
            }
        )
        extra.update(photo_urls)
        saved.extra = extra
        db.add(saved)
        db.commit()

    return {
        "client_id": item.client_id,
        "success": True,
        "message": message,
        "card_id": card_id,
        "item_id": int(saved.id) if saved else None,
        "inv_num": format_inv_num(saved.inv_num) if saved and saved.inv_num is not None else str(inv_num),
        "photos": photo_urls,
    }


def brigade_stats(db: Session, tenant_id: UUID, user: User, establishment_id: int | None) -> dict[str, Any]:
    items_today = att._count_items_for_user_today(db, tenant_id, user.id)
    cards = _open_cards_for_user(db, tenant_id, user.id)
    session = None
    if establishment_id:
        try:
            session = att.get_my_session_state(db, tenant_id, user, establishment_id)
        except ValueError:
            session = None
    start = datetime.combine(_today_lima(), datetime.min.time()).replace(tzinfo=LIMA_TZ)
    recent = db.execute(
        select(m.InvItemRegistrationLog, User)
        .outerjoin(User, User.id == m.InvItemRegistrationLog.user_id)
        .where(
            m.InvItemRegistrationLog.tenant_id == tenant_id,
            m.InvItemRegistrationLog.created_at >= start,
        )
        .order_by(m.InvItemRegistrationLog.created_at.desc())
        .limit(30)
    ).all()
    team = []
    for log, member in recent:
        team.append(
            {
                "user_id": str(log.user_id) if log.user_id else None,
                "full_name": member.full_name if member else "Brigada",
                "inv_num": log.inv_num,
                "created_at": log.created_at.isoformat() if log.created_at else None,
                "minutes_ago": _minutes_ago(log.created_at),
            }
        )
    return {
        "user": {"id": str(user.id), "full_name": user.full_name},
        "work_date": _today_lima().isoformat(),
        "items_inventoried_today": items_today,
        "open_cards": cards,
        "session": session,
        "team_activity": team,
    }


def _open_cards_for_user(db: Session, tenant_id: UUID, user_id: UUID) -> list[dict[str, Any]]:
    assigned = (
        select(m.InvCard)
        .where(
            m.InvCard.tenant_id == tenant_id,
            or_(m.InvCard.id_inventariador == user_id, m.InvCard.id_digitador == user_id),
        )
        .order_by(m.InvCard.state.asc(), m.InvCard.hoj_num.asc())
        .limit(200)
    )
    rows = db.scalars(assigned).all()
    if rows:
        return [_card_payload(db, c) for c in rows]
    all_cards = db.scalars(
        select(m.InvCard)
        .where(m.InvCard.tenant_id == tenant_id)
        .order_by(m.InvCard.state.asc(), m.InvCard.hoj_num.asc())
        .limit(200)
    ).all()
    return [_card_payload(db, c) for c in all_cards]


def _open_card_for_ambiente(
    db: Session, tenant_id: UUID, user_id: UUID, id_ambiente: int
) -> dict[str, Any] | None:
    card = db.scalar(
        select(m.InvCard)
        .where(
            m.InvCard.tenant_id == tenant_id,
            m.InvCard.state == 1,
            m.InvCard.id_ambiente == id_ambiente,
            or_(m.InvCard.id_inventariador == user_id, m.InvCard.id_digitador == user_id),
        )
        .order_by(m.InvCard.id.desc())
        .limit(1)
    )
    return _card_payload(db, card) if card else None


def _card_payload(db: Session, card: m.InvCard) -> dict[str, Any]:
    env = db.get(m.InvEnvironment, card.id_ambiente) if card.id_ambiente else None
    est = db.get(m.InvEstablishment, env.establishment_id) if env and env.establishment_id else None
    person = db.get(m.InvPerson, card.id_usuario) if card.id_usuario else None
    cc = db.get(m.InvCostCenter, card.id_ccosto) if card.id_ccosto else None
    return {
        "id": int(card.id),
        "hoj_num": format_hoj_num(card.hoj_num) if card.hoj_num is not None else None,
        "hoj_fec": card.hoj_fec.isoformat() if card.hoj_fec else None,
        "hoj_can_tot": card.hoj_can_tot,
        "state": card.state,
        "id_ambiente": card.id_ambiente,
        "id_ccosto": card.id_ccosto,
        "id_usuario": card.id_usuario,
        "ambiente": _ambiente_label(env),
        "local": _local_label(est),
        "usuario": _person_label(person),
        "centro_costo": f"{cc.code} - {cc.description}".strip(" -") if cc else None,
        "establishment_id": est.id if est else None,
    }


def _next_hoj_num(db: Session, tenant_id: UUID, user: User) -> int:
    current = user.num_act
    if current:
        taken = db.scalar(
            select(m.InvCard.id).where(m.InvCard.tenant_id == tenant_id, m.InvCard.hoj_num == current)
        )
        if not taken:
            return int(current)
    max_hoj = db.scalar(select(func.max(m.InvCard.hoj_num)).where(m.InvCard.tenant_id == tenant_id)) or 0
    nxt = int(max_hoj) + 1
    if user.num_fin and nxt > int(user.num_fin):
        raise ValueError("Se agotó el rango de números de hoja asignado al usuario")
    return nxt
