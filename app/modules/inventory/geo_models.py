"""Catálogos geográficos (Pais / Departamento / Provincia / Distrito) — sin tenant ni timestamps."""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class InvCountry(Base):
    """`countries` — Pais."""

    __tablename__ = "countries"

    id: Mapped[str] = mapped_column(String(2), primary_key=True)
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class InvDepartment(Base):
    """`departments` — Departamento."""

    __tablename__ = "departments"

    id: Mapped[str] = mapped_column(String(2), primary_key=True)
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    provinces: Mapped[list["InvProvince"]] = relationship(back_populates="department")


class InvProvince(Base):
    """`provinces` — Provincia."""

    __tablename__ = "provinces"

    id: Mapped[str] = mapped_column(String(4), primary_key=True)
    department_id: Mapped[str] = mapped_column(
        String(2), ForeignKey("departments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    department: Mapped["InvDepartment"] = relationship(back_populates="provinces")
    districts: Mapped[list["InvDistrict"]] = relationship(back_populates="province")


class InvDistrict(Base):
    """`districts` — Distrito."""

    __tablename__ = "districts"

    id: Mapped[str] = mapped_column(String(6), primary_key=True)
    province_id: Mapped[str] = mapped_column(
        String(4), ForeignKey("provinces.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    description: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    province: Mapped["InvProvince"] = relationship(back_populates="districts")
