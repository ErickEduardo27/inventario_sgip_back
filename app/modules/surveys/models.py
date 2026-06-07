import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPKMixin


class Survey(Base, UUIDPKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """Encuesta simple por WhatsApp."""

    __tablename__ = "surveys"

    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    response_type: Mapped[str] = mapped_column(String(40), nullable=False, default="si_no")
    options: Mapped[list[str]] = mapped_column(ARRAY(String(200)), nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="activo")

    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("segments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    response_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SurveyResponse(Base, UUIDPKMixin, TenantMixin, TimestampMixin):
    """Respuesta de un contacto a una encuesta (opcionalmente ligada a una campaña)."""

    __tablename__ = "survey_responses"

    survey_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("surveys.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("campaigns.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    contact_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    responded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
