import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPKMixin


class Contact(Base, UUIDPKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """Contacto que recibirá mensajes WhatsApp."""

    __tablename__ = "contacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "whatsapp_number", name="uq_contacts_tenant_whatsapp"),
    )

    first_name: Mapped[str] = mapped_column(String(150), nullable=False)
    last_name: Mapped[str] = mapped_column(String(150), nullable=False, default="")
    whatsapp_number: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True, index=True)
    document: Mapped[str | None] = mapped_column(String(50), nullable=True)

    site_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("catalog_sites.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    area_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("catalog_areas.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    position_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("catalog_positions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    region: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(40), nullable=False, default="activo", index=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)

    omnichannel_last_read_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
