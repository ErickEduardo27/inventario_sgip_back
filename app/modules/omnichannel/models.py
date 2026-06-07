import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPKMixin


class OmnichannelMessage(Base, UUIDPKMixin, TenantMixin, TimestampMixin):
    """Mensaje en el hilo de un contacto (correo u otros canales)."""

    __tablename__ = "omnichannel_messages"

    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    wa_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    wa_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    wa_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    wa_conversation_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    wa_conversation_origin_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    wa_billable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    wa_pricing_model: Mapped[str | None] = mapped_column(String(32), nullable=True)
    wa_pricing_category: Mapped[str | None] = mapped_column(String(64), nullable=True)
    wa_price_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    wa_pricing_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
