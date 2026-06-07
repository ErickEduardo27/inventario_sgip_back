from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import TimestampMixin, UUIDPKMixin


class Tenant(Base, UUIDPKMixin, TimestampMixin):
    """Empresa cliente del SaaS."""

    __tablename__ = "tenants"

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="active", nullable=False)
    plan_code: Mapped[str] = mapped_column(String(50), default="enterprise", nullable=False)
    timezone: Mapped[str] = mapped_column(String(100), default="America/Lima", nullable=False)
    locale: Mapped[str] = mapped_column(String(20), default="es-PE", nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="PEN", nullable=False)
