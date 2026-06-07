from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPKMixin


class CatalogSite(Base, UUIDPKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "catalog_sites"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_catalog_sites_tenant_name"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)


class CatalogArea(Base, UUIDPKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "catalog_areas"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_catalog_areas_tenant_name"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)


class CatalogPosition(Base, UUIDPKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    __tablename__ = "catalog_positions"
    __table_args__ = (UniqueConstraint("tenant_id", "name", name="uq_catalog_positions_tenant_name"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
