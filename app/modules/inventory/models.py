"""Modelos alineados con tablas tenant de SAP-GrupoISO (Laravel) + `tenant_id` para multi-tenant en una sola BD."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.json_text import NullableJSONText
from app.db.mixins import TenantMixin, TimestampMixin

from app.modules.inventory.geo_models import InvCountry, InvDepartment, InvDistrict, InvProvince  # noqa: F401


class InvEstablishment(Base, TenantMixin, TimestampMixin):
    """Locales / `establishments` (Laravel `Locales`)."""

    __tablename__ = "establishments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    country_id: Mapped[str | None] = mapped_column(
        String(2), ForeignKey("countries.id", ondelete="SET NULL"), nullable=True, index=True
    )
    department_id: Mapped[str | None] = mapped_column(
        String(2), ForeignKey("departments.id", ondelete="SET NULL"), nullable=True, index=True
    )
    province_id: Mapped[str | None] = mapped_column(
        String(4), ForeignKey("provinces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    district_id: Mapped[str | None] = mapped_column(
        String(6), ForeignKey("districts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    telephone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    trade_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    web_address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    aditional_information: Mapped[str | None] = mapped_column(Text, nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    photo_mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    photo_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    photo_token: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        unique=True,
        index=True,
    )
    customer_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("persons.id", ondelete="SET NULL"), nullable=True, index=True
    )

    pais: Mapped["InvCountry | None"] = relationship(foreign_keys=[country_id])
    departamento: Mapped["InvDepartment | None"] = relationship(foreign_keys=[department_id])
    provincia: Mapped["InvProvince | None"] = relationship(foreign_keys=[province_id])
    distrito: Mapped["InvDistrict | None"] = relationship(foreign_keys=[district_id])
    ambientes: Mapped[list["InvEnvironment"]] = relationship(back_populates="establishment")


class InvPerson(Base, TenantMixin, TimestampMixin):
    """`persons` (Laravel `Personas`)."""

    __tablename__ = "persons"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    identity_document_type_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    number: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    trade_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    country_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    department_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    province_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    district_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    telephone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    enviroment_code: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    cc_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    observation: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)


class InvCostCenter(Base, TenantMixin, TimestampMixin):
    """`cost_center` (Laravel `CostoCentro`)."""

    __tablename__ = "cost_center"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_inv_cost_center_tenant_code"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(70), nullable=False, default="")
    personal_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("persons.id", ondelete="SET NULL"), nullable=True
    )
    principal_center_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("cost_center.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_create: Mapped[str | None] = mapped_column(String(200), nullable=True)


class InvEnvironment(Base, TenantMixin, TimestampMixin):
    """`enviroments` (Laravel `Ambientes`, nombre de tabla con typo histórico)."""

    __tablename__ = "enviroments"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    establishment_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    floor: Mapped[str | None] = mapped_column(String(100), nullable=True)
    observation: Mapped[str | None] = mapped_column(Text, nullable=True)
    telephone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    anex: Mapped[str | None] = mapped_column(String(100), nullable=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, default="", index=True)
    image: Mapped[str | None] = mapped_column(String(500), nullable=True)
    user_create: Mapped[str | None] = mapped_column(String(200), nullable=True)

    establishment: Mapped["InvEstablishment"] = relationship(back_populates="ambientes")
    cards: Mapped[list["InvCard"]] = relationship(back_populates="ambiente")


class InvMargesiItem(Base, TenantMixin, TimestampMixin):
    """Catálogo / patrimonio `margesi` (Laravel ``Item``). Columnas físicas + ``extra`` residual."""

    __tablename__ = "margesi"
    __table_args__ = (
        CheckConstraint("mar_est IN ('N','B','R','M','I')", name="ck_margesi_mar_est"),
        CheckConstraint("mar_uso IN ('S','N')", name="ck_margesi_mar_uso"),
        CheckConstraint("mar_seg IN ('S','N')", name="ck_margesi_mar_seg"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    inv_num: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    inv_hoj: Mapped[str | None] = mapped_column(String(100), nullable=True)
    inv_sit: Mapped[str | None] = mapped_column(String(15), nullable=True)
    inv_con: Mapped[str | None] = mapped_column(String(10), nullable=True)
    mar_cpat: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    mar_des: Mapped[str | None] = mapped_column(String(120), nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(NullableJSONText, nullable=True)
    mar_nant: Mapped[str | None] = mapped_column(String(30), nullable=True)
    mar_num: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)
    mar_npri: Mapped[str | None] = mapped_column(String(30), nullable=True)
    mar_ccat: Mapped[str | None] = mapped_column(String(12), nullable=True)
    mar_esp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_col: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_mar: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mar_mod: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_ser: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_med: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_tip: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_npla: Mapped[str | None] = mapped_column(String(30), nullable=True)
    mar_nmot: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mar_ncha: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mar_ano: Mapped[str | None] = mapped_column(String(10), nullable=True)
    mar_obs: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mar_eti: Mapped[str | None] = mapped_column(String(10), nullable=True)
    mar_flag: Mapped[str | None] = mapped_column(String(5), nullable=True)
    mar_foto: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mar_foto2: Mapped[str | None] = mapped_column(String(200), nullable=True)
    amb_cod: Mapped[str | None] = mapped_column(String(20), nullable=True)
    usu_cod: Mapped[str | None] = mapped_column(String(20), nullable=True)
    usu_resp_cod: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cct_cod: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inv_sit_ant: Mapped[str | None] = mapped_column(String(50), nullable=True)
    inv_ver_sit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    inv_ver_obs: Mapped[str | None] = mapped_column(String(500), nullable=True)
    user_create: Mapped[str | None] = mapped_column(String(20), nullable=True)
    local_libre: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ccosto_libre: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ambiente_libre: Mapped[str | None] = mapped_column(String(500), nullable=True)
    usuario_libre: Mapped[str | None] = mapped_column(String(500), nullable=True)
    campo_libre: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mar_sit_conta: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mar_ing_tip: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mar_ing_fuente: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_ing_gasto: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_ing_siaf: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mar_ing_dini: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_ing_dadq: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_ing_ding: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_ing_cta: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mar_ing_dasi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_tas_doc: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_rev_doc: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_cont_doc: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_cont_cta: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mar_sit_gral: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mar_baj_causal: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_baj_res: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_baj_tdisp: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_baj_rdis: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_baj_benef: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mar_baj_elim_x: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mar_est: Mapped[str] = mapped_column(String(1), nullable=False, default="B")
    mar_uso: Mapped[str] = mapped_column(String(1), nullable=False, default="S")
    mar_seg: Mapped[str] = mapped_column(String(1), nullable=False, default="S")
    inv_num_1: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    inv_num_2: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mar_ing_fdini: Mapped[date | None] = mapped_column(Date, nullable=True)
    mar_ing_fdadq: Mapped[date | None] = mapped_column(Date, nullable=True)
    mar_ing_fding: Mapped[date | None] = mapped_column(Date, nullable=True)
    mar_ing_fdasi: Mapped[date | None] = mapped_column(Date, nullable=True)
    mar_tas_fec: Mapped[date | None] = mapped_column(Date, nullable=True)
    mar_rev_fec: Mapped[date | None] = mapped_column(Date, nullable=True)
    mar_cont_fec: Mapped[date | None] = mapped_column(Date, nullable=True)
    mar_baj_fres: Mapped[date | None] = mapped_column(Date, nullable=True)
    mar_baj_fdis: Mapped[date | None] = mapped_column(Date, nullable=True)
    inv_ver_fecha: Mapped[date | None] = mapped_column(Date, nullable=True)
    mar_ing_val: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_ing_vdep: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_ing_vutil: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_ing_pdep: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_ing_edad: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_tas_val: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_tas_vutil: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_rev_vutil: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_rev_pdep: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_rev_edad: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_rev_vdep: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_cont_val: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_cont_vutil: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_cont_pdep: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_cont_edad: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_cont_depm: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_hist: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_net_hist: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_acum: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_net_val: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_m01: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_m02: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_m03: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_m04: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_m05: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_m06: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_m07: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_m08: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_m09: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_m10: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_m11: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_m12: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    mar_dep_m13: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)


class InvCard(Base, TenantMixin, TimestampMixin):
    """Hoja de captura `cards`."""

    __tablename__ = "cards"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    hoj_num: Mapped[str] = mapped_column(String(50), nullable=False, default="", index=True)
    hoj_fec: Mapped[date | None] = mapped_column(Date, nullable=True)
    hoj_can_tot: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    id_ambiente: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("enviroments.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    id_ccosto: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cost_center.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    id_usuario: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("persons.id", ondelete="SET NULL"), nullable=True
    )
    id_digitador: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    id_inventariador: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    hoj_c_con: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hoj_c_sob: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hoj_e_nue: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hoj_e_bue: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hoj_e_reg: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hoj_e_mal: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hoj_e_ins: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hoj_e_rae: Mapped[str | None] = mapped_column(String(50), nullable=True)
    flag_firma: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    nota_interna: Mapped[str | None] = mapped_column(Text, nullable=True)
    nota_ficha: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    pdf: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pdf2: Mapped[str | None] = mapped_column(String(500), nullable=True)

    ambiente: Mapped["InvEnvironment"] = relationship(back_populates="cards")
    items: Mapped[list["InvItemCard"]] = relationship(
        back_populates="card", cascade="all, delete-orphan", order_by="InvItemCard.id"
    )


class InvItemCard(Base, TenantMixin, TimestampMixin):
    """Bien inventariado en hoja `itemcards` (Laravel `ItemTarjeta`)."""

    __tablename__ = "itemcards"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_card: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inv_num: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    mar_cpat: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    mar_num: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mar_des: Mapped[str | None] = mapped_column(String(500), nullable=True)
    inv_sit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inv_con: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inv_num_1: Mapped[str | None] = mapped_column(String(100), nullable=True)
    inv_num_2: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amb_cod_his: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_sit_conta: Mapped[str | None] = mapped_column(String(100), nullable=True)
    id_margesi: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("margesi.id", ondelete="SET NULL"), nullable=True, index=True
    )
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    card: Mapped["InvCard"] = relationship(back_populates="items")
    margesi_row: Mapped["InvMargesiItem | None"] = relationship()


class InvListSbn(Base, TenantMixin, TimestampMixin):
    """Catálogo SBN `list_sbn`."""

    __tablename__ = "list_sbn"
    __table_args__ = (UniqueConstraint("tenant_id", "code", name="uq_inv_list_sbn_tenant_code"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    cat_des: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cat_ulti: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cat_clase: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cat_cat: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cat_cont_vutil: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cat_cont_pdep: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cat_cont_gasto: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cat_cont_cta_a: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cat_cont_cta_o: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cat_cont_valp: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cat_uso: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cat_raa: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cat_foto: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cat_obs: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_create: Mapped[str | None] = mapped_column(String(200), nullable=True)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
