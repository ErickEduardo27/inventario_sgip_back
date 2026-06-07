from __future__ import annotations

import json
import smtplib
import ssl
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from uuid import UUID

from sqlalchemy import Select, exists, func, or_, select, text
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.modules.contacts.models import Contact
from app.modules.omnichannel.models import OmnichannelMessage
from app.modules.omnichannel.schemas import (
    ChatMessageOut,
    ChatThreadOut,
    SendWhatsAppTemplateBody,
    WhatsAppApprovedTemplateOut,
    WhatsAppSessionStatusOut,
)
from app.modules.templates.meta_graph import (
    normalize_whatsapp_template_language,
    sample_text_for_template_variable,
)
from app.modules.templates.models import MessageTemplate

_PREVIEW_ROW = (
    func.row_number()
    .over(
        partition_by=OmnichannelMessage.contact_id,
        order_by=OmnichannelMessage.created_at.desc(),
    )
    .label("rn")
)


def _digits_only_phone(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit())


def _chat_message_out(m: OmnichannelMessage) -> ChatMessageOut:
    price = float(m.wa_price_usd) if m.wa_price_usd is not None else None
    return ChatMessageOut(
        id=m.id,
        thread_id=m.contact_id,
        body=m.body,
        direction="inbound" if m.direction == "inbound" else "outbound",
        sent_at=m.created_at,
        status=m.status,
        channel=m.channel,
        subject=m.subject,
        wa_delivered_at=m.wa_delivered_at,
        wa_read_at=m.wa_read_at,
        wa_billable=m.wa_billable,
        wa_pricing_category=m.wa_pricing_category,
        wa_pricing_model=m.wa_pricing_model,
        wa_conversation_id=m.wa_conversation_id,
        wa_conversation_origin_type=m.wa_conversation_origin_type,
        wa_price_usd=price,
        wa_pricing_snapshot=m.wa_pricing_snapshot,
    )


class OmnichannelService:
    def __init__(self, db: Session):
        self.db = db

    def list_whatsapp_approved_templates(self, tenant_id: UUID) -> list[WhatsAppApprovedTemplateOut]:
        rows = list(
            self.db.scalars(
                select(MessageTemplate)
                .where(
                    MessageTemplate.tenant_id == tenant_id,
                    MessageTemplate.is_deleted.is_(False),
                    func.upper(func.coalesce(MessageTemplate.wa_review_status, "")) == "APPROVED",
                    MessageTemplate.wa_meta_name.isnot(None),
                    MessageTemplate.wa_meta_name != "",
                )
                .order_by(MessageTemplate.name)
            ).all()
        )
        return [
            WhatsAppApprovedTemplateOut(
                id=r.id,
                name=r.name,
                wa_meta_name=(r.wa_meta_name or "").strip(),
                wa_language=(r.wa_language or "es").strip() or "es",
                wa_header_format=(r.wa_header_format or "").strip() or None,
                wa_header_image_stored=bool(r.wa_header_image_blob and r.wa_header_image_token),
            )
            for r in rows
        ]

    def _customer_care_window_hours(self) -> int:
        return get_settings().whatsapp_customer_care_window_hours

    def _last_whatsapp_inbound_at(self, tenant_id: UUID, contact_id: UUID) -> datetime | None:
        return self.db.scalar(
            select(func.max(OmnichannelMessage.created_at)).where(
                OmnichannelMessage.tenant_id == tenant_id,
                OmnichannelMessage.contact_id == contact_id,
                OmnichannelMessage.channel == "whatsapp",
                OmnichannelMessage.direction == "inbound",
            )
        )

    def _whatsapp_session_is_open(self, tenant_id: UUID, contact_id: UUID) -> bool:
        last = self._last_whatsapp_inbound_at(tenant_id, contact_id)
        if last is None:
            return False
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return now < last + timedelta(hours=self._customer_care_window_hours())

    def whatsapp_session_status(self, tenant_id: UUID, contact_id: UUID) -> WhatsAppSessionStatusOut:
        self._get_contact(tenant_id, contact_id)
        hours = self._customer_care_window_hours()
        last = self._last_whatsapp_inbound_at(tenant_id, contact_id)
        if last is None:
            return WhatsAppSessionStatusOut(
                session_open=False,
                last_inbound_whatsapp_at=None,
                window_expires_at=None,
                window_hours=hours,
            )
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        expires = last + timedelta(hours=hours)
        now = datetime.now(timezone.utc)
        return WhatsAppSessionStatusOut(
            session_open=now < expires,
            last_inbound_whatsapp_at=last,
            window_expires_at=expires,
            window_hours=hours,
        )

    def _whatsapp_graph_post_messages(self, payload: dict) -> tuple[dict, str]:
        settings = get_settings()
        token = settings.whatsapp_access_token.strip()
        phone_number_id = settings.whatsapp_phone_number_id.strip()
        if not token or not phone_number_id:
            raise AppError(
                "WhatsApp Cloud API no configurada. Define WHATSAPP_ACCESS_TOKEN y "
                "WHATSAPP_PHONE_NUMBER_ID en el servidor.",
                503,
            )
        version = (settings.whatsapp_graph_api_version or "v25.0").strip().lstrip("/")
        url = f"https://graph.facebook.com/{version}/{phone_number_id}/messages"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read().decode("utf-8")
                parsed = json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                msg = err_json.get("error", {}).get("message", err_body)
            except json.JSONDecodeError:
                msg = err_body or str(e)
            raise AppError(f"WhatsApp API: {msg}", 502) from e
        except OSError as e:
            raise AppError(f"No se pudo contactar a WhatsApp API: {e}", 502) from e

        wa_msg_id = ""
        try:
            mids = parsed.get("messages") or []
            if mids and isinstance(mids[0], dict):
                wa_msg_id = str(mids[0].get("id") or "")
        except (TypeError, KeyError, IndexError):
            wa_msg_id = ""
        return parsed, wa_msg_id

    def _get_contact(self, tenant_id: UUID, contact_id: UUID) -> Contact:
        c = self.db.scalar(
            select(Contact).where(
                Contact.id == contact_id,
                Contact.tenant_id == tenant_id,
                Contact.is_deleted.is_(False),
            )
        )
        if not c:
            raise AppError("Contacto no encontrado", 404)
        return c

    def list_threads(self, tenant_id: UUID, search: str | None) -> list[ChatThreadOut]:
        q = (search or "").strip()
        term = f"%{q}%" if q else None

        preview_sq = (
            select(
                OmnichannelMessage.contact_id.label("cid"),
                OmnichannelMessage.body,
                OmnichannelMessage.channel,
                OmnichannelMessage.created_at,
                _PREVIEW_ROW,
            ).where(OmnichannelMessage.tenant_id == tenant_id)
        ).subquery()

        last_only = (
            select(
                preview_sq.c.cid,
                preview_sq.c.body,
                preview_sq.c.channel,
                preview_sq.c.created_at,
            ).where(preview_sq.c.rn == 1)
        ).subquery()

        stmt: Select[tuple[Contact, str | None, str | None, datetime | None]] = (
            select(Contact, last_only.c.body, last_only.c.channel, last_only.c.created_at)
            .outerjoin(last_only, last_only.c.cid == Contact.id)
            .where(Contact.tenant_id == tenant_id, Contact.is_deleted.is_(False))
            .order_by(
                last_only.c.created_at.desc().nulls_last(),
                Contact.first_name,
                Contact.last_name,
            )
        )

        if term:
            msg_match = exists(
                select(1).where(
                    OmnichannelMessage.contact_id == Contact.id,
                    OmnichannelMessage.tenant_id == tenant_id,
                    OmnichannelMessage.body.ilike(term),
                )
            )
            contact_match = or_(
                Contact.first_name.ilike(term),
                Contact.last_name.ilike(term),
                func.concat(Contact.first_name, " ", Contact.last_name).ilike(term),
                Contact.whatsapp_number.ilike(term),
                func.coalesce(Contact.email, "").ilike(term),
                func.coalesce(Contact.document, "").ilike(term),
            )
            stmt = stmt.where(or_(contact_match, msg_match))

        rows = self.db.execute(stmt).all()
        contact_ids = [row[0].id for row in rows]
        unread_map: dict[UUID, int] = {}
        if contact_ids:
            epoch = text("'epoch'::timestamptz")
            uc_stmt = (
                select(OmnichannelMessage.contact_id, func.count(OmnichannelMessage.id))
                .select_from(OmnichannelMessage)
                .join(Contact, Contact.id == OmnichannelMessage.contact_id)
                .where(
                    OmnichannelMessage.tenant_id == tenant_id,
                    OmnichannelMessage.contact_id.in_(contact_ids),
                    OmnichannelMessage.direction == "inbound",
                    OmnichannelMessage.created_at > func.coalesce(Contact.omnichannel_last_read_at, epoch),
                )
                .group_by(OmnichannelMessage.contact_id)
            )
            unread_map = {cid: int(cnt) for cid, cnt in self.db.execute(uc_stmt).all()}

        out: list[ChatThreadOut] = []
        for row in rows:
            c = row[0]
            preview = row[1]
            last_ch = row[2]
            last_at = row[3]
            name = f"{c.first_name} {c.last_name}".strip() or c.first_name
            out.append(
                ChatThreadOut(
                    id=c.id,
                    contact_name=name,
                    whatsapp_number=c.whatsapp_number,
                    email=c.email,
                    contact_status=c.status,
                    last_message_preview=(preview[:180] + "…") if preview and len(preview) > 180 else preview,
                    last_message_at=last_at,
                    last_channel=last_ch,
                    unread_count=unread_map.get(c.id, 0),
                )
            )
        return out

    def list_messages(self, tenant_id: UUID, thread_id: UUID) -> list[ChatMessageOut]:
        c = self._get_contact(tenant_id, thread_id)
        msgs = list(
            self.db.scalars(
                select(OmnichannelMessage)
                .where(
                    OmnichannelMessage.tenant_id == tenant_id,
                    OmnichannelMessage.contact_id == thread_id,
                )
                .order_by(OmnichannelMessage.created_at.asc())
            ).all()
        )
        out = [_chat_message_out(m) for m in msgs]
        mx: datetime | None = None
        for m in msgs:
            t = m.created_at
            if t is None:
                continue
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if mx is None or t > mx:
                mx = t
        if mx is not None:
            cur = c.omnichannel_last_read_at
            if cur is not None and cur.tzinfo is None:
                cur = cur.replace(tzinfo=timezone.utc)
            if cur is None or mx > cur:
                c.omnichannel_last_read_at = mx
                self.db.commit()
        return out

    def append_message(self, tenant_id: UUID, thread_id: UUID, body: str) -> ChatMessageOut:
        self._get_contact(tenant_id, thread_id)
        text = body.strip()
        if not text:
            raise AppError("El mensaje no puede estar vacío", 400)
        m = OmnichannelMessage(
            tenant_id=tenant_id,
            contact_id=thread_id,
            channel="whatsapp",
            direction="outbound",
            body=text,
            status="enviado",
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _chat_message_out(m)

    def send_email(self, tenant_id: UUID, contact_id: UUID, subject: str | None, body: str) -> ChatMessageOut:
        settings = get_settings()
        if not settings.smtp_host.strip():
            raise AppError(
                "Envío por correo no configurado. Define SMTP_HOST (y credenciales) en el servidor.",
                503,
            )
        c = self._get_contact(tenant_id, contact_id)
        if not (c.email and c.email.strip()):
            raise AppError("El contacto no tiene correo electrónico registrado", 400)
        text = body.strip()
        if not text:
            raise AppError("El cuerpo del mensaje no puede estar vacío", 400)
        subj = (subject or "").strip() or "Mensaje desde Conectados Directo"

        msg = EmailMessage()
        msg["Subject"] = subj
        msg["From"] = settings.smtp_from.strip() or settings.smtp_user
        msg["To"] = c.email.strip()
        msg.set_content(text)

        try:
            if settings.smtp_use_ssl:
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(
                    settings.smtp_host, settings.smtp_port, timeout=45, context=context
                ) as smtp:
                    if settings.smtp_user:
                        smtp.login(settings.smtp_user, settings.smtp_password or "")
                    smtp.send_message(msg)
            else:
                with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=45) as smtp:
                    if settings.smtp_use_tls:
                        smtp.starttls(context=ssl.create_default_context())
                    if settings.smtp_user:
                        smtp.login(settings.smtp_user, settings.smtp_password or "")
                    smtp.send_message(msg)
        except OSError as e:
            raise AppError(f"No se pudo enviar el correo: {e}", 502) from e
        except smtplib.SMTPException as e:
            raise AppError(f"Error SMTP: {e}", 502) from e

        m = OmnichannelMessage(
            tenant_id=tenant_id,
            contact_id=contact_id,
            channel="email",
            direction="outbound",
            body=text,
            subject=subj,
            status="enviado",
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _chat_message_out(m)

    def send_whatsapp_template(
        self,
        tenant_id: UUID,
        contact_id: UUID,
        body: SendWhatsAppTemplateBody,
    ) -> ChatMessageOut:
        c = self._get_contact(tenant_id, contact_id)
        to_digits = _digits_only_phone(c.whatsapp_number)
        if not to_digits:
            raise AppError("El contacto no tiene un número de WhatsApp válido", 400)

        variables: list[str] = []
        display_name: str
        tpl_row: MessageTemplate | None = None
        if body.template_id is not None:
            tpl = self.db.scalar(
                select(MessageTemplate).where(
                    MessageTemplate.id == body.template_id,
                    MessageTemplate.tenant_id == tenant_id,
                    MessageTemplate.is_deleted.is_(False),
                )
            )
            if not tpl:
                raise AppError("Plantilla no encontrada", 404)
            st = (tpl.wa_review_status or "").strip().upper()
            if st != "APPROVED":
                raise AppError(
                    "Solo puedes enviar plantillas aprobadas por Meta. Estado actual: "
                    f"{tpl.wa_review_status or 'sin registrar'}.",
                    400,
                )
            wa_name = (tpl.wa_meta_name or "").strip()
            if not wa_name:
                raise AppError("La plantilla no tiene nombre en Meta.", 400)
            lang = normalize_whatsapp_template_language((tpl.wa_language or "es_ES").strip())
            variables = list(tpl.variables or [])
            display_name = tpl.name
            tpl_row = tpl
        else:
            wa_name = (body.template_name or "").strip()
            if not wa_name:
                raise AppError("Indica la plantilla del CRM (aprobada) o el nombre técnico en Meta.", 400)
            lang = normalize_whatsapp_template_language((body.language_code or "es_ES").strip())
            display_name = wa_name

        template_block: dict = {"name": wa_name, "language": {"code": lang}}
        components: list[dict] = []

        if tpl_row is not None and (tpl_row.wa_header_format or "").strip().upper() == "IMAGE":
            url = ""
            if tpl_row.wa_header_image_token and tpl_row.wa_header_image_blob:
                base = get_settings().public_api_base_url.strip().rstrip("/")
                if not base.startswith("https://"):
                    raise AppError(
                        "Configura PUBLIC_API_BASE_URL (HTTPS) en el servidor para enviar plantillas con imagen "
                        "guardada en el CRM.",
                        503,
                    )
                url = f"{base}/api/public/template-header-image/{tpl_row.wa_header_image_token}"
            if not url.startswith("https://"):
                url = (body.header_image_url or "").strip()
            if not url.startswith("https://"):
                raise AppError(
                    "Esta plantilla tiene cabecera de imagen: guarda una imagen al crearla o indica header_image_url "
                    "(HTTPS público).",
                    400,
                )
            components.append(
                {
                    "type": "header",
                    "parameters": [{"type": "image", "image": {"link": url}}],
                }
            )
        elif body.template_id is None and (body.header_image_url or "").strip().startswith("https://"):
            url = (body.header_image_url or "").strip()
            components.append(
                {
                    "type": "header",
                    "parameters": [{"type": "image", "image": {"link": url}}],
                }
            )

        if variables:
            components.append(
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": sample_text_for_template_variable(v)} for v in variables
                    ],
                }
            )

        if components:
            template_block["components"] = components

        payload = {
            "messaging_product": "whatsapp",
            "to": to_digits,
            "type": "template",
            "template": template_block,
        }
        _parsed, wa_msg_id = self._whatsapp_graph_post_messages(payload)

        body_lines = [
            f'Plantilla WhatsApp "{display_name}" ({lang}, Meta: {wa_name}).',
        ]
        if wa_msg_id:
            body_lines.append(f"ID mensaje: {wa_msg_id}")

        m = OmnichannelMessage(
            tenant_id=tenant_id,
            contact_id=contact_id,
            channel="whatsapp",
            direction="outbound",
            body="\n".join(body_lines),
            status="enviado",
            wa_message_id=wa_msg_id or None,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _chat_message_out(m)

    def send_whatsapp_session_text(self, tenant_id: UUID, contact_id: UUID, body: str) -> ChatMessageOut:
        """Envía mensaje de texto de sesión (solo dentro de la ventana tras último mensaje entrante del cliente)."""
        if not self._whatsapp_session_is_open(tenant_id, contact_id):
            h = self._customer_care_window_hours()
            raise AppError(
                f"No hay ventana de sesión de WhatsApp abierta (últimos {h} h desde el último mensaje del cliente). "
                "Usa una plantilla aprobada para volver a contactar.",
                400,
            )
        c = self._get_contact(tenant_id, contact_id)
        to_digits = _digits_only_phone(c.whatsapp_number)
        if not to_digits:
            raise AppError("El contacto no tiene un número de WhatsApp válido", 400)
        text = body.strip()
        if not text:
            raise AppError("El mensaje no puede estar vacío", 400)

        payload = {
            "messaging_product": "whatsapp",
            "to": to_digits,
            "type": "text",
            "text": {"preview_url": False, "body": text[:4096]},
        }
        _, wa_msg_id = self._whatsapp_graph_post_messages(payload)

        m = OmnichannelMessage(
            tenant_id=tenant_id,
            contact_id=contact_id,
            channel="whatsapp",
            direction="outbound",
            body=text[:4096],
            status="enviado",
            wa_message_id=wa_msg_id or None,
        )
        self.db.add(m)
        self.db.commit()
        self.db.refresh(m)
        return _chat_message_out(m)
