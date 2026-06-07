import uuid
from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Table, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPKMixin

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", UUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
)


class Role(Base, UUIDPKMixin, TimestampMixin, SoftDeleteMixin):
    """Rol IAM. Si `tenant_id` es NULL es un rol global del sistema (template)."""

    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_roles_tenant_code"),)

    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class UIComponent(Base, UUIDPKMixin, TimestampMixin):
    """Catálogo global de componentes/pantallas del sidebar."""

    __tablename__ = "ui_components"

    code: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    group_name: Mapped[str] = mapped_column(String(100), nullable=False)
    route: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_portal: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")


class RoleComponent(Base, TimestampMixin):
    """Pivote rol ↔ componente con permisos CRUD+export y alcance (scope)."""

    __tablename__ = "role_components"

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        primary_key=True,
    )
    component_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ui_components.id", ondelete="CASCADE"),
        primary_key=True,
    )
    can_view: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    can_create: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_edit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_delete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_export: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="tenant")


class User(Base, UUIDPKMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """Usuario interno del portal Conectados Directo."""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),)

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    last_access_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_superadmin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    num_ini: Mapped[int | None] = mapped_column(Integer, nullable=True)
    num_fin: Mapped[int | None] = mapped_column(Integer, nullable=True)
    num_act: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eti_ini: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eti_fin: Mapped[int | None] = mapped_column(Integer, nullable=True)
    eti_act: Mapped[int | None] = mapped_column(Integer, nullable=True)

    roles: Mapped[list["Role"]] = relationship(
        "Role",
        secondary=user_roles,
        lazy="selectin",
    )

    @property
    def role_ids(self) -> list[uuid.UUID]:
        return [r.id for r in self.roles]
