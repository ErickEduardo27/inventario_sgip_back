"""Modelos alineados con tablas tenant de SAP-GrupoISO (Laravel) + `tenant_id` para multi-tenant en una sola BD."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
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
    __table_args__ = (UniqueConstraint("tenant_id", "hoj_num", name="uq_cards_tenant_hoj_num"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    hoj_num: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
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
    __table_args__ = (UniqueConstraint("tenant_id", "inv_num", name="uq_itemcards_tenant_inv_num"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    id_card: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("cards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    inv_num: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
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


class InvImportJob(Base, TenantMixin, TimestampMixin):
    """Trabajo de importación masiva (archivo en GCS + procesamiento Celery)."""

    __tablename__ = "import_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    module: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    gcs_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    registered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    errors: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    extra: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class InvDescargaArchivo(Base, TenantMixin, TimestampMixin):
    """Exportación CSV asíncrona (Celery → GCS → URL firmada)."""

    __tablename__ = "descarga_archivos"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    module: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    gcs_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    download_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_size_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    errors: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )


class InvItemRegistrationLog(Base, TenantMixin):
    """Registro append-only de creación de bienes por usuario (estadísticas)."""

    __tablename__ = "item_registration_logs"
    __table_args__ = (
        Index("ix_item_reg_log_tenant_user", "tenant_id", "user_id"),
        Index("ix_item_reg_log_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    itemcard_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    card_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    inv_num: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class InvItemAuditLog(Base, TenantMixin):
    """Auditoría append-only de bienes inventariados (crear / editar / eliminar)."""

    __tablename__ = "item_audit_logs"
    __table_args__ = (
        Index("ix_item_audit_log_tenant_created", "tenant_id", "created_at"),
        Index("ix_item_audit_log_tenant_action", "tenant_id", "action"),
        Index("ix_item_audit_log_tenant_user", "tenant_id", "user_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    action: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    itemcard_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True, index=True)
    card_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    inv_num: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    mar_des: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class InvUserAssignedBienes(Base, TenantMixin, TimestampMixin):
    """Bienes asignados a un inventariador según sus hojas de captura (poblado por script SQL)."""

    __tablename__ = "user_assigned_bienes"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uq_user_assigned_bienes_tenant_user"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    total_bienes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_hojas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InvReporteAptotCache(Base, TenantMixin):
    """Cache materializado del reporte APTOT descarga total.

    ``source_kind``: ``conciliado`` | ``sobrante`` | ``faltante``
    """

    __tablename__ = "reporte_aptot_cache"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_kind", "source_ref_id", name="uq_reporte_aptot_cache_source"),
        Index("ix_reporte_aptot_cache_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ref_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    itemcard_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    mar_sit_conta: Mapped[str | None] = mapped_column(String(50), nullable=True)
    mar_cpat: Mapped[str | None] = mapped_column(String(200), nullable=True)
    state: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inv_sit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    inv_con: Mapped[str | None] = mapped_column(String(20), nullable=True)
    mar_npri: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_num: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mar_ccat: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_des: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mar_esp: Mapped[str | None] = mapped_column(String(500), nullable=True)
    mar_est: Mapped[str | None] = mapped_column(String(10), nullable=True)
    mar_uso: Mapped[str | None] = mapped_column(String(10), nullable=True)
    mar_seg: Mapped[str | None] = mapped_column(String(10), nullable=True)
    mar_col: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mar_mar: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mar_mod: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mar_tip: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mar_ser: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mar_med: Mapped[str | None] = mapped_column(String(200), nullable=True)
    mar_npla: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_nmot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_ncha: Mapped[str | None] = mapped_column(String(100), nullable=True)
    mar_obs: Mapped[str | None] = mapped_column(Text, nullable=True)
    inv_num_1: Mapped[str | None] = mapped_column(String(100), nullable=True)
    inv_num_2: Mapped[str | None] = mapped_column(String(100), nullable=True)
    inv_num: Mapped[str | None] = mapped_column(String(100), nullable=True)
    item_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    item_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    hoj_num: Mapped[str | None] = mapped_column(String(50), nullable=True)
    hoj_fec: Mapped[date | None] = mapped_column(Date, nullable=True)
    area_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    area_description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ambiente_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ambiente_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ambiente_piso: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ambiente_piso_des: Mapped[str | None] = mapped_column(String(100), nullable=True)
    local_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    local_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    local_departamento: Mapped[str | None] = mapped_column(String(200), nullable=True)
    usuario_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    usuario: Mapped[str | None] = mapped_column(String(500), nullable=True)
    fecha_margesi: Mapped[date | None] = mapped_column(Date, nullable=True)
    doc_margesi: Mapped[str | None] = mapped_column(String(200), nullable=True)
    cuenta_margesi: Mapped[str | None] = mapped_column(String(100), nullable=True)
    valor_margesi: Mapped[Decimal | None] = mapped_column(Numeric(16, 2), nullable=True)
    margesi_sbn: Mapped[str | None] = mapped_column(String(100), nullable=True)
    margesi_area: Mapped[str | None] = mapped_column(String(200), nullable=True)
    margesi_departamento: Mapped[str | None] = mapped_column(String(200), nullable=True)
    margesi_local: Mapped[str | None] = mapped_column(String(500), nullable=True)
    margesi_ambiente: Mapped[str | None] = mapped_column(String(500), nullable=True)
    margesi_usuario: Mapped[str | None] = mapped_column(String(500), nullable=True)
    margesi_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    margesi_marca: Mapped[str | None] = mapped_column(String(200), nullable=True)
    margesi_modelo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    margesi_tipo: Mapped[str | None] = mapped_column(String(200), nullable=True)
    margesi_serie: Mapped[str | None] = mapped_column(String(200), nullable=True)
    margesi_cod_local: Mapped[str | None] = mapped_column(String(100), nullable=True)
    local_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    margesi_obs: Mapped[str | None] = mapped_column(Text, nullable=True)
    local_libre: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ccosto_libre: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ambiente_libre: Mapped[str | None] = mapped_column(String(500), nullable=True)
    usuario_libre: Mapped[str | None] = mapped_column(String(500), nullable=True)
    campo_libre: Mapped[str | None] = mapped_column(String(500), nullable=True)


class InvDashboardEstablishmentStat(Base, TenantMixin):
    """Totales materializados por local para el dashboard (lectura rápida)."""

    __tablename__ = "dashboard_establishment_stats"
    __table_args__ = (
        UniqueConstraint("tenant_id", "establishment_id", name="uq_dashboard_est_stats_tenant_est"),
        Index("ix_dashboard_est_stats_tenant", "tenant_id"),
        Index("ix_dashboard_est_stats_tenant_code", "tenant_id", "establishment_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    establishment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("establishments.id", ondelete="CASCADE"),
        nullable=False,
    )
    establishment_code: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    establishment_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    margesi_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    margesi_conciliado: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    margesi_faltantes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    margesi_no_inventariable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inventario_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inventario_conciliado: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inventario_sobrante: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inventario_no_conciliable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    refreshed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class InvReporteLocal(Base, TenantMixin, TimestampMixin):
    """Seguimiento de inventario por local (Reporte Locales)."""

    __tablename__ = "reporte_locales"
    __table_args__ = (
        UniqueConstraint("tenant_id", "establishment_id", name="uq_reporte_locales_tenant_est"),
        Index("ix_reporte_locales_tenant", "tenant_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    establishment_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("establishments.id", ondelete="CASCADE"),
        nullable=False,
    )
    fecha_inventario_propuesto: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_inventario_real: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_inicio_cronograma: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_cierre_cronograma: Mapped[date | None] = mapped_column(Date, nullable=True)
    fotos_urls: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    pdfs_urls: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, default=list)
    grupo: Mapped[str | None] = mapped_column(String(50), nullable=True)
    nota: Mapped[str | None] = mapped_column(Text, nullable=True)
    situacion: Mapped[str] = mapped_column(String(32), nullable=False, default="pendiente")


class InvReporteAptotCacheMeta(Base):
    """Estado de la última reconstrucción del cache APTOT por tenant."""

    __tablename__ = "reporte_aptot_cache_meta"

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        primary_key=True,
    )
    refreshed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
