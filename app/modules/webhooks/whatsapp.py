"""Webhook de WhatsApp Cloud API (Meta): verificación GET y eventos POST."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.modules.contacts.models import Contact
from app.modules.omnichannel.models import OmnichannelMessage
from app.modules.templates.models import MessageTemplate
from app.modules.tenants.models import Tenant

logger = logging.getLogger("conectados_directo.webhooks.whatsapp")

router = APIRouter(tags=["webhooks"])

_WA_STATUS_TO_DB = {
    "sent": "enviado",
    "delivered": "entregado",
    "read": "leido",
    "failed": "fallido",
    "deleted": "eliminado",
}

# Orden para no degradar estado si Meta reenvía eventos desordenados
_STATUS_RANK = {
    "fallido": 0,
    "eliminado": 0,
    "enviado": 1,
    "entregado": 2,
    "leido": 3,
}


def _digits(raw: str | None) -> str:
    if not raw:
        return ""
    return "".join(c for c in raw if c.isdigit())


def verify_meta_signature(payload: bytes, signature_header: str | None, app_secret: str) -> bool:
    if not app_secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected_hex = signature_header[7:]
    digest = hmac.new(app_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, expected_hex)


def _map_wa_status(raw: str | None) -> str | None:
    if not raw:
        return None
    return _WA_STATUS_TO_DB.get(raw.strip().lower())


def _status_rank(status: str | None) -> int:
    if not status:
        return 0
    return _STATUS_RANK.get(status, 0)


def _parse_wa_unix_ts(raw: object) -> datetime | None:
    try:
        sec = int(str(raw).strip())
        return datetime.fromtimestamp(sec, tz=timezone.utc)
    except (ValueError, TypeError, AttributeError):
        return None


def _extract_price_usd(pricing: dict) -> Decimal | None:
    for key in ("amount", "total_price", "price", "cost", "value", "total_amount"):
        v = pricing.get(key)
        if v is None:
            continue
        try:
            return Decimal(str(v))
        except (ValueError, TypeError, ArithmeticError, InvalidOperation):
            continue
    return None


def _apply_pricing_and_conversation_from_status(msg: OmnichannelMessage, st: dict) -> None:
    if "pricing" in st:
        pricing = st.get("pricing")
        if isinstance(pricing, dict) and pricing:
            msg.wa_pricing_snapshot = pricing
            if "billable" in pricing:
                msg.wa_billable = bool(pricing["billable"])
            pm = pricing.get("pricing_model")
            if isinstance(pm, str) and pm.strip():
                msg.wa_pricing_model = pm.strip()[:32]
            cat = pricing.get("category")
            if isinstance(cat, str) and cat.strip():
                msg.wa_pricing_category = cat.strip()[:64]
            price = _extract_price_usd(pricing)
            if price is not None:
                msg.wa_price_usd = price

    if "conversation" in st:
        conv = st.get("conversation")
        if isinstance(conv, dict) and conv:
            cid = conv.get("id")
            if isinstance(cid, str) and cid.strip():
                msg.wa_conversation_id = cid.strip()[:128]
            origin = conv.get("origin")
            if isinstance(origin, dict):
                ot = origin.get("type")
                if isinstance(ot, str) and ot.strip():
                    msg.wa_conversation_origin_type = ot.strip()[:40]


def _find_message_by_wa_id(db: Session, wa_id: str) -> OmnichannelMessage | None:
    if not wa_id:
        return None
    row = db.scalar(select(OmnichannelMessage).where(OmnichannelMessage.wa_message_id == wa_id))
    if row:
        return row
    return db.scalar(
        select(OmnichannelMessage).where(
            OmnichannelMessage.channel == "whatsapp",
            OmnichannelMessage.direction == "outbound",
            OmnichannelMessage.body.like(f"%{wa_id}%"),
        )
    )


def _apply_status_updates(db: Session, statuses: list) -> None:
    items = [x for x in statuses if isinstance(x, dict)]
    items.sort(key=lambda d: int(str(d.get("timestamp") or "0").strip() or "0"))

    for st in items:
        wa_id = st.get("id")
        if not wa_id:
            continue
        msg = _find_message_by_wa_id(db, str(wa_id))
        if not msg:
            logger.info("Estado WhatsApp sin fila local: id=%s payload=%s", wa_id, st.get("status"))
            continue

        estado_raw = st.get("status")
        db_status = _map_wa_status(estado_raw if isinstance(estado_raw, str) else None)
        ts = _parse_wa_unix_ts(st.get("timestamp"))

        if db_status:
            current = msg.status
            if _status_rank(db_status) >= _status_rank(current):
                msg.status = db_status
            if db_status == "entregado" and ts and msg.wa_delivered_at is None:
                msg.wa_delivered_at = ts
            if db_status == "leido" and ts:
                msg.wa_read_at = ts
                if msg.wa_delivered_at is None:
                    msg.wa_delivered_at = ts

        _apply_pricing_and_conversation_from_status(msg, st)
        db.add(msg)

    db.commit()


def _resolve_default_tenant_id(db: Session) -> UUID | None:
    settings = get_settings()
    t = db.scalar(select(Tenant).where(Tenant.slug == settings.default_tenant_slug))
    return t.id if t else None


def _find_contact_by_from_digits(db: Session, tenant_id: UUID, from_digits: str) -> Contact | None:
    """Empareja por dígitos exactos o por sufijo (p. ej. CRM guarda 999… y Meta envía 51…)."""
    rows = list(
        db.scalars(
            select(Contact).where(Contact.tenant_id == tenant_id, Contact.is_deleted.is_(False))
        ).all()
    )
    if not from_digits or len(from_digits) < 8:
        return None
    exact: list[Contact] = []
    fuzzy: list[tuple[int, Contact]] = []
    for c in rows:
        cd = _digits(c.whatsapp_number)
        if not cd:
            continue
        if cd == from_digits:
            exact.append(c)
        elif len(cd) >= 8 and (from_digits.endswith(cd) or cd.endswith(from_digits)):
            fuzzy.append((len(cd), c))
    if exact:
        return exact[0]
    if fuzzy:
        fuzzy.sort(key=lambda x: -x[0])
        return fuzzy[0][1]
    return None


def _profile_name_for_wa_id(value: dict, from_digits: str) -> str | None:
    raw = value.get("contacts")
    if not isinstance(raw, list):
        return None
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        wa_id = _digits(str(entry.get("wa_id") or ""))
        if wa_id != from_digits:
            continue
        profile = entry.get("profile")
        if isinstance(profile, dict):
            name = (profile.get("name") or "").strip()
            return name or None
    return None


def _get_or_create_contact_for_inbound(
    db: Session, tenant_id: UUID, from_digits: str, value: dict
) -> Contact | None:
    c = _find_contact_by_from_digits(db, tenant_id, from_digits)
    if c:
        return c
    if len(from_digits) < 8:
        logger.info("Mensaje entrante: número demasiado corto from=%s", from_digits)
        return None
    first = (_profile_name_for_wa_id(value, from_digits) or "WhatsApp").strip()[:150] or "WhatsApp"
    c = Contact(
        tenant_id=tenant_id,
        first_name=first,
        last_name="",
        whatsapp_number=from_digits,
        status="activo",
    )
    try:
        with db.begin_nested():
            db.add(c)
            db.flush()
    except IntegrityError:
        return _find_contact_by_from_digits(db, tenant_id, from_digits)
    logger.info("Contacto creado desde webhook WhatsApp: %s (%s)", first, from_digits)
    return c


def _extract_text_body(msg: dict) -> str:
    mtype = (msg.get("type") or "").lower()
    if mtype == "text":
        t = msg.get("text")
        if isinstance(t, dict):
            return (t.get("body") or "").strip()
    return ""


def _apply_inbound_messages(db: Session, value: dict) -> None:
    tenant_id = _resolve_default_tenant_id(db)
    if not tenant_id:
        logger.warning("Webhook WhatsApp: no hay tenant con slug default_tenant_slug")
        return

    messages = value.get("messages") or []
    for msg in messages:
        if not isinstance(msg, dict):
            continue
        wa_mid = str(msg.get("id") or "").strip()
        if wa_mid:
            dup = db.scalar(
                select(OmnichannelMessage).where(
                    OmnichannelMessage.wa_message_id == wa_mid,
                    OmnichannelMessage.direction == "inbound",
                )
            )
            if dup:
                continue

        from_digits = _digits(str(msg.get("from") or ""))
        if not from_digits:
            continue
        contact = _get_or_create_contact_for_inbound(db, tenant_id, from_digits, value)
        if not contact:
            continue

        body = _extract_text_body(msg)
        if not body:
            body = f"[WhatsApp tipo: {msg.get('type') or 'desconocido'}]"

        m = OmnichannelMessage(
            tenant_id=tenant_id,
            contact_id=contact.id,
            channel="whatsapp",
            direction="inbound",
            body=body,
            status=None,
            wa_message_id=wa_mid or None,
        )
        db.add(m)
    db.commit()


def _apply_template_status_update(db: Session, value: dict) -> None:
    """Actualiza estado de revisión Meta desde `message_template_status_update`."""
    name = str(value.get("message_template_name") or value.get("name") or "").strip()
    if not name:
        return
    lang = str(value.get("message_template_language") or value.get("language") or "").strip()
    ev = str(
        value.get("event")
        or value.get("message_template_status")
        or value.get("status")
        or ""
    ).strip().upper()
    reason = value.get("reason")
    reason_s = str(reason).strip() if reason is not None and str(reason).strip() else None

    rows = list(
        db.scalars(
            select(MessageTemplate).where(
                MessageTemplate.wa_meta_name == name,
                MessageTemplate.is_deleted.is_(False),
            )
        ).all()
    )
    tpl: MessageTemplate | None = None
    for r in rows:
        if lang and r.wa_language and (r.wa_language or "").strip() != lang:
            continue
        tpl = r
        break
    if tpl is None and rows:
        tpl = rows[0]
    if not tpl:
        logger.info("template_status_update: sin plantilla local wa_meta_name=%s", name)
        return

    if ev:
        tpl.wa_review_status = ev[:40]
    if reason_s and reason_s.upper() not in ("NONE", "NONE_PROVIDED", ""):
        tpl.wa_review_reason = reason_s[:2000]
    db.add(tpl)
    db.commit()


def process_whatsapp_webhook_payload(data: dict) -> None:
    if not data:
        return
    entries = data.get("entry")
    if not isinstance(entries, list):
        return

    with SessionLocal() as db:
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            changes = entry.get("changes")
            if not isinstance(changes, list):
                continue
            for change in changes:
                if not isinstance(change, dict):
                    continue
                value = change.get("value")
                if not isinstance(value, dict):
                    continue

                field = change.get("field")
                if isinstance(field, str) and field == "message_template_status_update":
                    _apply_template_status_update(db, value)
                    continue

                statuses = value.get("statuses")
                if isinstance(statuses, list) and statuses:
                    _apply_status_updates(db, statuses)

                messages = value.get("messages")
                if isinstance(messages, list) and messages:
                    _apply_inbound_messages(db, value)


def run_whatsapp_webhook_job(payload: dict) -> None:
    try:
        process_whatsapp_webhook_payload(payload)
    except Exception:
        logger.exception("Fallo al procesar webhook WhatsApp")


def _verify_token_expected() -> str:
    settings = get_settings()
    return settings.whatsapp_webhook_verify_token.strip()


@router.get("/whatsapp")
@router.get("/whatsapp/")
def whatsapp_webhook_verify(
    hub_mode: str | None = Query(None, alias="hub.mode"),
    hub_verify_token: str | None = Query(None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(None, alias="hub.challenge"),
):
    """Verificación de suscripción de Meta (desafío hub.challenge).

    Meta llama con GET y query `hub.mode`, `hub.verify_token`, `hub.challenge`.
    Abrir solo la URL en el navegador no incluye esos parámetros: no es un fallo del servidor.
    """
    expected = _verify_token_expected()

    if hub_mode is None and hub_verify_token is None and hub_challenge is None:
        return PlainTextResponse(
            content=(
                "Webhook WhatsApp listo.\n\n"
                "Meta verifica con GET agregando query params (no al abrir esta URL sola en el navegador):\n"
                "  hub.mode=subscribe&hub.verify_token=TU_TOKEN&hub.challenge=...\n\n"
                "En .env define WHATSAPP_WEBHOOK_VERIFY_TOKEN con el mismo valor que "
                '"Verify token" en el panel de Meta.'
            ),
            media_type="text/plain; charset=utf-8",
        )

    if hub_mode != "subscribe":
        raise HTTPException(status_code=403, detail="Se esperaba hub.mode=subscribe (callback de Meta).")

    if not expected:
        raise HTTPException(
            status_code=503,
            detail="Configura WHATSAPP_WEBHOOK_VERIFY_TOKEN en el servidor (mismo valor que Verify token en Meta).",
        )

    if hub_verify_token != expected:
        raise HTTPException(status_code=403, detail="Verification failed: hub.verify_token no coincide.")

    return PlainTextResponse(content=hub_challenge or "", media_type="text/plain; charset=utf-8")


@router.post("/whatsapp")
@router.post("/whatsapp/")
async def whatsapp_webhook_receive(request: Request, background_tasks: BackgroundTasks):
    """Recibe eventos de Meta; responde al instante y procesa en segundo plano."""
    raw = await request.body()
    settings = get_settings()
    secret = settings.whatsapp_app_secret.strip()
    if secret:
        sig = request.headers.get("X-Hub-Signature-256")
        if not verify_meta_signature(raw, sig, secret):
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        data = json.loads(raw.decode("utf-8")) if raw else {}
    except json.JSONDecodeError:
        logger.warning("Webhook WhatsApp: cuerpo JSON inválido")
        return {"status": "ok"}

    if not isinstance(data, dict):
        return {"status": "ok"}

    background_tasks.add_task(run_whatsapp_webhook_job, data)
    return {"status": "ok"}
