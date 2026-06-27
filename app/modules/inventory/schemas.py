"""Esquemas Pydantic para inventario (respuestas tipo Laravel `success` / `message`)."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.inventory_numbers import parse_inventory_number


class OkPayload(BaseModel):
    success: bool = True
    message: str = ""
    id: int | None = None


class PagedMeta(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int


class PagedRows(BaseModel):
    data: list[dict[str, Any]]
    meta: PagedMeta


def _empty_str_to_none(v: object) -> object:
    if v is None:
        return None
    if isinstance(v, str):
        s = v.strip()
        return s if s else None
    return v


class EstablishmentWrite(BaseModel):
    id: int | None = None
    description: str = ""
    country_id: str | None = None
    department_id: str | None = None
    province_id: str | None = None
    district_id: str | None = None
    address: str | None = None
    email: str | None = None
    telephone: str | None = None

    @field_validator(
        "country_id",
        "department_id",
        "province_id",
        "district_id",
        "address",
        "email",
        "telephone",
        "trade_address",
        "web_address",
        "aditional_information",
        mode="before",
    )
    @classmethod
    def blank_optional_to_none(cls, v: object) -> object:
        return _empty_str_to_none(v)
    code: str = ""
    trade_address: str | None = None
    web_address: str | None = None
    aditional_information: str | None = None
    customer_id: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    photo_base64: str | None = Field(
        default=None,
        max_length=1_200_000,
        description="JPEG/PNG/WebP en base64 o data URL (subida comprimida desde el cliente).",
    )
    photo_mime: str | None = Field(default=None, max_length=80)
    photo_clear: bool = Field(default=False, description="Si true, elimina la foto guardada del local.")


class PersonWrite(BaseModel):
    id: int | None = None
    type: str | None = None
    identity_document_type_id: str | None = None
    number: str | None = None
    name: str | None = None
    trade_name: str | None = None
    enviroment_code: str | None = None
    cc_code: str | None = None
    email: str | None = None
    telephone: str | None = None
    address: str | None = None
    observation: str | None = None
    enabled: bool = True
    extra: dict[str, Any] | None = None


class CostCenterWrite(BaseModel):
    id: int | None = None
    code: str = ""
    description: str = Field(default="", max_length=70)
    personal_id: int | None = None
    principal_center_id: int | None = None
    user_create: str | None = None


class EnvironmentWrite(BaseModel):
    id: int | None = None
    description: str | None = None
    establishment_id: int
    floor: str | None = None
    observation: str | None = None
    telephone: str | None = None
    anex: str | None = None
    code: str = ""
    image: str | None = None
    user_create: str | None = None


class CardWrite(BaseModel):
    id: int | None = None
    hoj_num: int = 0
    hoj_fec: date | None = None
    hoj_can_tot: int = 0
    id_ambiente: int
    id_ccosto: int
    id_usuario: int | None = None
    id_inventariador: UUID | None = None
    id_digitador: UUID | None = None
    hoj_c_con: str | None = None
    hoj_c_sob: str | None = None
    hoj_e_nue: str | None = None
    hoj_e_bue: str | None = None
    hoj_e_reg: str | None = None
    hoj_e_mal: str | None = None
    hoj_e_ins: str | None = None
    hoj_e_rae: str | None = None
    flag_firma: bool = False
    nota_interna: str | None = None
    nota_ficha: str | None = None
    state: int = 1

    @field_validator("hoj_num", mode="before")
    @classmethod
    def _coerce_hoj_num(cls, v: object) -> int:
        return parse_inventory_number(v, field="Número de hoja", allow_empty=True)


class CardItemWrite(BaseModel):
    """Cuerpo alineado con `CardsController::storeItem` (crear/actualizar ítem de hoja)."""

    id: int | None = None
    id_margesi: int | None = None
    no_conciliar: bool = False
    mar_cpat_num: str = ""
    inv_num: int | None = None
    inv_num_1: str | None = None
    inv_num_2: str | None = None
    mar_ano: str | None = None
    mar_ccat: str | None = None
    mar_col: str | None = None
    mar_cpat: str | None = None
    mar_des: str | None = None
    mar_esp: str | None = None
    mar_est: str | None = None
    mar_eti: str | None = None
    mar_flag: str | None = None
    mar_foto: str | None = None
    mar_foto2: str | None = None
    mar_foto3: str | None = None
    mar_mar: str | None = None
    mar_med: str | None = None
    mar_mod: str | None = None
    mar_ncha: str | None = None
    mar_nmot: str | None = None
    mar_npla: str | None = None
    mar_npri: str | None = None
    mar_num: str | None = None
    mar_obs: str | None = None
    mar_seg: str | None = None
    mar_ser: str | None = None
    mar_tip: str | None = None
    mar_uso: str | None = None

    @field_validator("inv_num", mode="before")
    @classmethod
    def _coerce_inv_num(cls, v: object) -> int | None:
        if v is None or v == "":
            return None
        return parse_inventory_number(v, field="Número de inventario")


class ItemCardTranslate(BaseModel):
    id_card_old: int
    id_card: int


class ListSbnWrite(BaseModel):
    id: int | None = None
    code: str = ""
    cat_des: str | None = None
    cat_ulti: str | None = None
    cat_clase: str | None = None
    cat_cat: str | None = None
    cat_cont_vutil: str | None = None
    cat_cont_pdep: str | None = None
    cat_cont_gasto: str | None = None
    cat_cont_cta_a: str | None = None
    cat_cont_cta_o: str | None = None
    cat_cont_valp: str | None = None
    cat_uso: str | None = None
    cat_raa: str | None = None
    cat_foto: str | None = None
    cat_obs: str | None = None
    user_create: str | None = None
    extra: dict[str, Any] | None = None


class MargesiWrite(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int | None = None
    inv_num: str | None = None
    inv_hoj: str | None = None
    inv_sit: str | None = None
    inv_con: str | None = None
    mar_cpat: str | None = None
    mar_des: str | None = None
    extra: dict[str, Any] | None = None


class RecordQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=15, ge=1, le=2000)
    column: str = "code"
    value: str | None = None
    search: str | None = None
    establishment_id: int | None = None
    column_ord: str | None = None
    ord_tipo: str = "asc"
    flag_firma: bool | None = None
    inv_sit_filter: Literal["C", "S", "N", "F"] | None = Field(
        default=None,
        description="C conciliados; F faltantes (margesi: vacío/guion); N no inventariable; S sobrantes (bienes)",
    )
    local_code: str | None = Field(
        default=None,
        description="Filtrar margesi donde amb_cod coincide con el código del local",
    )


class ItemPhotoQuery(RecordQuery):
    photo_slot: Literal[1, 2, 3] | None = Field(
        default=None,
        description="Filtrar por slot de foto (1, 2 o 3)",
    )


class ItemPhotoRow(BaseModel):
    itemcard_id: int
    card_id: int
    inv_num: int | str | None = None
    mar_cpat: str | None = None
    mar_des: str | None = None
    inv_sit: str | None = None
    hoj_num: int | str | None = None
    photo_slot: int
    photo_url: str


class InventoryMonthlyCount(BaseModel):
    month: str
    label: str
    bienes: int
    margesi: int


class InventoryDashboardKpis(BaseModel):
    bienes_total: int
    margesi_total: int


class InventoryUserRegistrationStat(BaseModel):
    user_id: str | None = None
    full_name: str | None = None
    email: str | None = None
    total: int


class InventoryDashboardResponse(BaseModel):
    kpis: InventoryDashboardKpis
    by_month: list[InventoryMonthlyCount]


class InventoryUserRegistrationsResponse(BaseModel):
    total: int
    by_user: list[InventoryUserRegistrationStat]


class DashboardEstablishmentStatRow(BaseModel):
    establishment_id: int
    establishment_code: str
    establishment_description: str | None = None
    margesi_total: int = 0
    margesi_conciliado: int = 0
    margesi_faltantes: int = 0
    margesi_no_inventariable: int = 0
    inventario_total: int = 0
    inventario_conciliado: int = 0
    inventario_sobrante: int = 0
    inventario_no_conciliable: int = 0


class DashboardEstablishmentStatsResponse(BaseModel):
    data: list[DashboardEstablishmentStatRow]
    meta: PagedMeta


ReporteLocalSituacion = Literal["pendiente", "en_proceso", "terminado"]


class ReporteLocalWrite(BaseModel):
    model_config = ConfigDict(extra="ignore")

    establishment_id: int
    fecha_inventario_propuesto: date | None = None
    fecha_inventario_real: date | None = None
    fotos_urls: list[str] = Field(default_factory=list)
    pdfs_urls: list[str] = Field(default_factory=list)
    grupo: str | None = Field(default=None, max_length=50)
    nota: str | None = None
    situacion: ReporteLocalSituacion = "pendiente"

    @field_validator("fotos_urls", "pdfs_urls", mode="before")
    @classmethod
    def _normalize_url_lists(cls, v: object) -> list[str]:
        if v is None:
            return []
        if not isinstance(v, list):
            return []
        return [str(x).strip() for x in v if str(x).strip()]

    @field_validator("nota", "grupo", mode="before")
    @classmethod
    def _strip_optional_text(cls, v: object) -> object:
        return _empty_str_to_none(v)


class ReporteLocalRow(BaseModel):
    establishment_id: int
    establishment_code: str
    establishment_description: str | None = None
    fecha_inventario_propuesto: date | None = None
    fecha_inventario_real: date | None = None
    fotos_urls: list[str] = Field(default_factory=list)
    pdfs_urls: list[str] = Field(default_factory=list)
    grupo: str | None = None
    nota: str | None = None
    situacion: ReporteLocalSituacion = "pendiente"


class ReporteLocalesListResponse(BaseModel):
    data: list[ReporteLocalRow]
    meta: PagedMeta


ReporteLocalFileKindFilter = Literal["all", "fotos", "pdfs"]


class ReporteLocalSignedUrlItem(BaseModel):
    src: str
    kind: Literal["foto", "pdf"]
    filename: str
    download_url: str
    expires_at: str | None = None


class ReporteLocalSignedUrlResponse(BaseModel):
    src: str
    kind: Literal["foto", "pdf"]
    filename: str
    download_url: str
    expires_at: str | None = None


class ReporteLocalSignedUrlsResponse(BaseModel):
    establishment_id: int
    establishment_code: str
    items: list[ReporteLocalSignedUrlItem] = Field(default_factory=list)


class ReporteLocalBulkDownloadRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    establishment_ids: list[int] | None = None
    department_id: str | None = None
    include_fotos: bool = True
    include_pdfs: bool = True


class AuditLogQuery(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=15, ge=1, le=200)
    column: str = "inv_num"
    value: str | None = None
    search: str | None = None
    column_ord: str | None = None
    ord_tipo: str = "asc"
    action: str | None = Field(default=None, description="create | update | delete")
    date_from: date | None = None
    date_to: date | None = None


class ConciliationFilters(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=15, ge=1, le=200)
    column_ord: str | None = Field(default=None, alias="columnOrd")
    ord_tipo: str = Field(default="asc", alias="ordTipo")
    codigo_interno: str | None = None
    codigo_sbn: str | None = None
    descripcion: str | None = None
    marca: str | None = None
    modelo: str | None = None
    local: str | None = None
    numero_hoja: str | None = None
    numero_inv: str | None = None
    situacion: str | None = Field(
        default=None,
        description="Filtro no-conciliación: todos | conciliable | no_conciliable",
    )


class ConciliationPairWrite(BaseModel):
    margesi: int = Field(..., description="ID margesi")
    bienes: int = Field(..., description="ID itemcard (bien inventariado)")


class DesconciliarWrite(BaseModel):
    itemcard: int = Field(..., description="ID itemcard conciliado")


class ConciliationSbnWrite(BaseModel):
    margesi: int
    bienes: int
    numero_hoja: str = Field(..., description="Número de hoja del bien (card_numero)")
    codigo_sbn: str = Field(..., description="Código SBN completo de 12 dígitos (Margesi)")


class DesconciliarSbnWrite(BaseModel):
    itemcard: int
    margesi: int


class NoConciliableMarkWrite(BaseModel):
    id: int
    tipo: str = Field(..., description="margesi | bien")
    observacion: str | None = None


class ImportConciliationRow(BaseModel):
    margesi_id: int
    bien_id: int
    inv_con: str | None = "1"


class ImportConciliationMatchRow(BaseModel):
    codigo_interno: str | None = None
    inv_num: str | None = None
    mar_cpat: str | None = None
    ord_conciliacion: str | None = None


class ImportNoConciliableMatchRow(BaseModel):
    codigo_interno: str | None = None
    inv_num: str | None = None
    observacion: str | None = None


class ImportConciliationMatchRequest(BaseModel):
    rows: list[ImportConciliationMatchRow]


class ImportNoConciliableMatchRequest(BaseModel):
    rows: list[ImportNoConciliableMatchRow]


class ImportDesconciliarRequest(BaseModel):
    item_ids: list[int]


class ImportConciliationResult(BaseModel):
    success: bool
    message: str
    registrados: list[dict[str, Any]]
    no_registrados: list[dict[str, Any]]


class EstablishmentImportResult(BaseModel):
    success: bool
    message: str
    total_rows: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = Field(default_factory=list)
    async_job: bool = False
    job_id: str | None = None


class EnvironmentImportResult(BaseModel):
    """Resultado importación ambientes (total incluye fila de encabezado)."""

    success: bool
    message: str
    total: int = 0
    registered: int = 0
    inserted: int = 0
    updated: int = 0
    errors: list[str] = Field(default_factory=list)
    async_job: bool = False
    job_id: str | None = None


class CostCenterImportResult(BaseModel):
    """Resultado importación centros de costo (total incluye fila de encabezado)."""

    success: bool
    message: str
    total: int = 0
    registered: int = 0
    inserted: int = 0
    updated: int = 0
    errors: list[str] = Field(default_factory=list)
    async_job: bool = False
    job_id: str | None = None


class PersonImportResult(BaseModel):
    """Resultado importación personas (total incluye fila de encabezado)."""

    success: bool
    message: str
    total: int = 0
    registered: int = 0
    inserted: int = 0
    updated: int = 0
    errors: list[str] = Field(default_factory=list)
    async_job: bool = False
    job_id: str | None = None


class ListSbnImportResult(BaseModel):
    """Resultado importación catálogo SBN. ``registered`` = solo altas (create), no actualizaciones."""

    success: bool
    message: str
    total: int = 0
    registered: int = 0
    updated: int = 0
    errors: list[str] = Field(default_factory=list)
    async_job: bool = False
    job_id: str | None = None


class MargesiImportResult(BaseModel):
    """Resultado importación Margesi. ``registered`` cuenta create y update; ``total`` incluye cabecera."""

    success: bool
    message: str
    total: int = 0
    registered: int = 0
    errors: list[str] = Field(default_factory=list)
    async_job: bool = False
    job_id: str | None = None


class HojaCapturaBulkPdfRequest(BaseModel):
    """Solicitud de PDF único con varias fichas de hoja de captura."""

    mode: Literal["range", "local"]
    hoj_num_from: int | None = Field(default=None, ge=0)
    hoj_num_to: int | None = Field(default=None, ge=0)
    establishment_id: int | None = Field(default=None, ge=1)


class HojaCapturaImportResult(BaseModel):
    success: bool
    message: str
    total: int = 0
    registered: int = 0
    inserted: int = 0
    updated: int = 0
    errors: list[str] = Field(default_factory=list)
    async_job: bool = False
    job_id: str | None = None


class ImportJobStatus(BaseModel):
    """Estado de trabajo de importación masiva (persistido en ``import_jobs``)."""

    job_id: str
    state: str
    progress: int = 0
    total_rows: int = 0
    processed: int = 0
    inserted: int = 0
    updated: int = 0
    registered: int = 0
    errors: list[str] = Field(default_factory=list)
    message: str = ""


class DescargaArchivoStartResponse(BaseModel):
    success: bool = True
    async_job: bool = True
    job_id: str
    message: str = ""


class DescargaArchivoStatus(BaseModel):
    """Estado de exportación CSV asíncrona (``descarga_archivos``)."""

    job_id: str
    module: str
    state: str
    progress: int = 0
    filename: str = ""
    file_size_bytes: int | None = None
    download_url: str | None = None
    expires_at: str | None = None
    errors: list[str] = Field(default_factory=list)
    message: str = ""


class EstablishmentImportJobStatus(BaseModel):
    job_id: str
    state: str
    progress: int = 0
    total_rows: int = 0
    processed: int = 0
    inserted: int = 0
    updated: int = 0
    errors: list[str] = Field(default_factory=list)
    message: str = ""


class UserInventoryConf(BaseModel):
    num_ini: int | None = None
    num_fin: int | None = None
    num_act: int | None = None
    eti_ini: int | None = None
    eti_fin: int | None = None
    eti_act: int | None = None


class InventoryNumWrite(BaseModel):
    num_act: int | None = None
    eti_act: int | None = None


class HojaCapturaTablesResponse(BaseModel):
    persons: list[dict[str, Any]]
    environments: list[dict[str, Any]]
    establishments: list[dict[str, Any]]
    cost_centers: list[dict[str, Any]]
    users: list[dict[str, Any]]
    user_conf: UserInventoryConf


class ItemCardTablesResponse(BaseModel):
    list_sbn: list[dict[str, Any]]
    user_conf: UserInventoryConf
    host: str | None = None


class MargesiLookupResult(BaseModel):
    success: bool = True
    message: str = ""
    esta_conciliado: bool = False
    inv_hoj: str | None = None
    id_margesi: int | None = None
    inv_num_sugerido: str | None = None
    item: dict[str, Any] | None = None
    card_info: dict[str, Any] | None = None


class ItemPhotoUploadResult(BaseModel):
    success: bool = True
    message: str = ""
    filename: str | None = None
    url: str | None = None
