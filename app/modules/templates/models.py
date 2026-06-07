from datetime import datetime
import uuid

from sqlalchemy import DateTime, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPKMixin


class MessageTemplate(Base, UUIDPKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """Plantilla reutilizable de mensaje WhatsApp con variables `{{var}}`."""

    __tablename__ = "message_templates"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_templates_tenant_name"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(60), nullable=False, default="comunicado", index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str]] = mapped_column(ARRAY(String(60)), nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="activo")

    wa_meta_name: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    wa_language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    wa_meta_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    wa_review_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    wa_review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    wa_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    wa_graph_template_id: Mapped[str | None] = mapped_column(String(128), nullable=True)

    wa_header_format: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        doc="Cabecera en Meta, p. ej. IMAGE (la URL de la imagen se envía al disparar la plantilla).",
    )
    wa_quick_reply_buttons: Mapped[list[str] | None] = mapped_column(
        ARRAY(String(40)),
        nullable=True,
        doc="Textos de botones QUICK_REPLY (máx. 3) incluidos al crear la plantilla en Meta.",
    )

    wa_header_image_mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    wa_header_image_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    wa_header_image_token: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
        unique=True,
        index=True,
    )

    @property
    def wa_header_image_available(self) -> bool:
        return bool(self.wa_header_image_blob and self.wa_header_image_token)
