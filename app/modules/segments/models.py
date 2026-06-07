import uuid

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPKMixin


class Segment(Base, UUIDPKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """Segmento dinámico construido a partir de criterios de filtrado."""

    __tablename__ = "segments"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_segments_tenant_name"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    criteria: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="activo")


class SegmentManualContact(Base):
    """Contactos incluidos manualmente en un segmento (además del filtro por criterios)."""

    __tablename__ = "segment_manual_contacts"

    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("segments.id", ondelete="CASCADE"),
        primary_key=True,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        primary_key=True,
    )
