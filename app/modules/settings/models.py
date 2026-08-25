from sqlalchemy import Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin, UUIDPKMixin


class WorkspaceSettings(Base, UUIDPKMixin, TenantMixin, TimestampMixin):
    """Configuración general del portal por tenant."""

    __tablename__ = "workspace_settings"
    __table_args__ = (UniqueConstraint("tenant_id", name="uq_workspace_settings_tenant"),)

    business_name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    business_sector: Mapped[str | None] = mapped_column(String(120), nullable=True)
    whatsapp_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    whatsapp_display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    connection_status: Mapped[str] = mapped_column(String(40), nullable=False, default="pendiente")

    cost_per_message: Mapped[float] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="PEN")
    timezone: Mapped[str] = mapped_column(String(80), nullable=False, default="America/Lima")
    logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pdf_logo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    google_cloud_info: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    alerts_config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    portal_branding: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    feature_flags: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    custom_components: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    integration_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
