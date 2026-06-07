from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_id
from app.core.exceptions import AppError
from app.db.session import get_db
from app.modules.iam.models import User
from app.modules.omnichannel.schemas import (
    ChatMessageCreate,
    ChatMessageOut,
    ChatThreadOut,
    SendEmailBody,
    SendWhatsAppSessionBody,
    SendWhatsAppTemplateBody,
    WhatsAppApprovedTemplateOut,
    WhatsAppSessionStatusOut,
)
from app.modules.omnichannel.service import OmnichannelService

router = APIRouter()


def _handle(err: AppError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.message)


@router.get("/whatsapp-approved-templates", response_model=list[WhatsAppApprovedTemplateOut])
def list_whatsapp_approved_templates(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    """Plantillas del CRM aprobadas en Meta (para envío desde omnicanal)."""
    return OmnichannelService(db).list_whatsapp_approved_templates(tenant_id)


@router.get("/threads", response_model=list[ChatThreadOut])
def get_threads(
    search: str | None = Query(default=None, description="Busca en nombres, teléfono, correo, documento o texto de mensajes"),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return OmnichannelService(db).list_threads(tenant_id, search=search)


@router.get("/threads/{thread_id}/messages", response_model=list[ChatMessageOut])
def get_messages(
    thread_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return OmnichannelService(db).list_messages(tenant_id, thread_id)
    except AppError as e:
        raise _handle(e) from e


@router.post("/threads/{thread_id}/messages", response_model=ChatMessageOut)
def post_message(
    thread_id: UUID,
    body: ChatMessageCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    """Registra un mensaje saliente tipo WhatsApp (sin envío real hasta integrar proveedor)."""
    try:
        return OmnichannelService(db).append_message(tenant_id, thread_id, body.body)
    except AppError as e:
        raise _handle(e) from e


@router.post("/threads/{contact_id}/send-email", response_model=ChatMessageOut)
def send_email_to_contact(
    contact_id: UUID,
    body: SendEmailBody,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    """Envía un correo al contacto (SMTP en servidor) y guarda el mensaje en el historial."""
    try:
        return OmnichannelService(db).send_email(tenant_id, contact_id, body.subject, body.body)
    except AppError as e:
        raise _handle(e) from e


@router.post("/threads/{contact_id}/send-whatsapp-template", response_model=ChatMessageOut)
def send_whatsapp_template_to_contact(
    contact_id: UUID,
    body: SendWhatsAppTemplateBody,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    """Envía una plantilla por WhatsApp Cloud API y registra el mensaje en base de datos."""
    try:
        return OmnichannelService(db).send_whatsapp_template(tenant_id, contact_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.get("/threads/{contact_id}/whatsapp-session", response_model=WhatsAppSessionStatusOut)
def get_whatsapp_customer_care_window(
    contact_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    """Estado de la ventana de sesión (texto libre) vs plantilla según último mensaje entrante del cliente."""
    try:
        return OmnichannelService(db).whatsapp_session_status(tenant_id, contact_id)
    except AppError as e:
        raise _handle(e) from e


@router.post("/threads/{contact_id}/send-whatsapp-session", response_model=ChatMessageOut)
def send_whatsapp_session_message(
    contact_id: UUID,
    body: SendWhatsAppSessionBody,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    """Envía texto de sesión por la API (solo si la ventana desde el último mensaje del cliente sigue abierta)."""
    try:
        return OmnichannelService(db).send_whatsapp_session_text(tenant_id, contact_id, body.body)
    except AppError as e:
        raise _handle(e) from e
