from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatThreadOut(BaseModel):
    id: UUID
    contact_name: str
    whatsapp_number: str
    email: str | None = None
    contact_status: str = Field(description="Estado del contacto en CRM (activo, observado, etc.)")
    last_message_preview: str | None = None
    last_message_at: datetime | None = None
    last_channel: str | None = Field(default=None, description="email | whatsapp — último mensaje")
    unread_count: int = 0


class ChatMessageOut(BaseModel):
    id: UUID
    thread_id: UUID
    body: str
    direction: str = Field(description="'inbound' | 'outbound'")
    sent_at: datetime
    status: str | None = Field(default=None, description="enviado, entregado, leido")
    channel: str = Field(default="whatsapp", description="email | whatsapp")
    subject: str | None = None
    wa_delivered_at: datetime | None = Field(default=None, description="Entrega al dispositivo (webhook Meta)")
    wa_read_at: datetime | None = Field(default=None, description="Lectura por el usuario (webhook Meta)")
    wa_billable: bool | None = Field(default=None, description="Facturable según Meta / BSP")
    wa_pricing_category: str | None = Field(default=None, description="Categoría de conversación (p. ej. marketing)")
    wa_pricing_model: str | None = Field(default=None, description="Modelo de precios (p. ej. CBP)")
    wa_conversation_id: str | None = Field(default=None, description="ID de conversación en Meta")
    wa_conversation_origin_type: str | None = Field(default=None, description="Origen (p. ej. service, referral)")
    wa_price_usd: float | None = Field(default=None, description="Importe si el webhook/BSP lo incluye")
    wa_pricing_snapshot: dict | None = Field(default=None, description="Objeto pricing tal cual del webhook")


class ChatMessageCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4096)


class SendEmailBody(BaseModel):
    body: str = Field(min_length=1, max_length=8192)
    subject: str | None = Field(default=None, max_length=500)


class SendWhatsAppTemplateBody(BaseModel):
    """Envío por nombre libre o por plantilla del CRM (solo si Meta la aprobó)."""

    template_id: UUID | None = Field(default=None, description="ID de message_templates aprobada en Meta")
    template_name: str = Field(default="", max_length=512, description="Nombre técnico en Meta (si no usas template_id)")
    language_code: str = Field(default="es_ES", min_length=2, max_length=35)
    header_image_url: str | None = Field(
        default=None,
        max_length=2048,
        description="URL HTTPS pública de la imagen del encabezado (plantillas con HEADER IMAGE en Meta).",
    )


class WhatsAppApprovedTemplateOut(BaseModel):
    id: UUID
    name: str
    wa_meta_name: str
    wa_language: str
    wa_header_format: str | None = Field(
        default=None,
        description='p. ej. "IMAGE" si la plantilla en Meta lleva cabecera de imagen.',
    )
    wa_header_image_stored: bool = Field(
        default=False,
        description="True si hay imagen guardada en el CRM (Meta la obtiene por URL pública del API).",
    )

    model_config = ConfigDict(from_attributes=True)


class WhatsAppSessionStatusOut(BaseModel):
    """Ventana de atención al cliente (mensajes de sesión vs plantilla)."""

    session_open: bool = Field(description="True si aún puedes enviar texto libre por la API de sesión")
    last_inbound_whatsapp_at: datetime | None = Field(
        default=None,
        description="Último mensaje entrante de WhatsApp del contacto (reinicia la ventana)",
    )
    window_expires_at: datetime | None = Field(
        default=None,
        description="Hasta cuándo aplica la ventana si está abierta",
    )
    window_hours: int = Field(default=24, description="Horas de ventana configuradas en el servidor")


class SendWhatsAppSessionBody(BaseModel):
    body: str = Field(min_length=1, max_length=4096, description="Texto de sesión (solo si la ventana está abierta)")
