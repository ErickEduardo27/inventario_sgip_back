"""Asistencia de inventariadores con geocerca y jornada."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import TenantMixin, TimestampMixin


class InvUserEstablishmentAssignment(Base, TenantMixin, TimestampMixin):
    """Establecimientos asignados a un inventariador."""

    __tablename__ = "user_establishment_assignments"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "establishment_id", name="uq_user_est_assignment"),
        Index("ix_user_est_assignment_user", "tenant_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    establishment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("establishments.id", ondelete="CASCADE"),
        nullable=False,
    )


class InvAttendanceSession(Base, TenantMixin, TimestampMixin):
    """Jornada de asistencia (una por usuario / establecimiento / día)."""

    __tablename__ = "attendance_sessions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "establishment_id",
            "work_date",
            name="uq_attendance_session_day",
        ),
        Index("ix_attendance_session_tenant_date", "tenant_id", "work_date"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    establishment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("establishments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    work_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="abierta")
    inventory_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    marks: Mapped[list["InvAttendanceMark"]] = relationship(
        back_populates="session",
        order_by="InvAttendanceMark.marked_at",
    )


class InvAttendanceMark(Base, TenantMixin):
    """Marcación puntual dentro de una jornada."""

    __tablename__ = "attendance_marks"
    __table_args__ = (Index("ix_attendance_marks_session", "session_id", "marked_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    establishment_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    mark_type: Mapped[str] = mapped_column(String(32), nullable=False)
    marked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    geofence_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="PRESENTE")
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_info: Mapped[str | None] = mapped_column(String(500), nullable=True)

    session: Mapped["InvAttendanceSession"] = relationship(back_populates="marks")


class InvAttendanceLocationSample(Base, TenantMixin):
    """Muestra GPS durante inventario activo (no rastreo continuo)."""

    __tablename__ = "attendance_location_samples"
    __table_args__ = (Index("ix_attendance_loc_sample_session", "session_id", "sampled_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        nullable=False,
    )
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    sampled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
