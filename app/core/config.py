import os
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_env_path)


def _default_database_url() -> str:
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "")
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "conectados_directo")
    return f"postgresql+psycopg2://{user}:{quote_plus(password)}@{host}:{port}/{db}"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_env_path), env_file_encoding="utf-8", extra="ignore")

    database_url: str = Field(default_factory=_default_database_url)
    default_tenant_slug: str = Field(default="default", description="Tenant usado si no se envía X-Tenant-ID")

    tenant_base_domains: str = Field(
        default="localhost,127.0.0.1",
        description="Dominios base (coma): si Host es `{slug}.<base>`, el slug identifica al tenant. "
        "Ej. `miempresa.com,app.onrender.com`. Para solo `localhost`, usa `localhost`.",
    )
    tenant_subdomain_strict: bool = Field(
        default=True,
        description="Si true y el subdominio no coincide con ningún tenant activo → 404. "
        "Si false → cae al tenant por defecto (útil en desarrollo).",
    )

    cors_extra_origins: str = Field(
        default="",
        description="Orígenes CORS adicionales separados por coma (ej. http://192.168.1.10:5173)",
    )
    frontend_url: str = Field(
        default="",
        description="URL pública del front (sin barra final). Se añade automáticamente a CORS en producción.",
        validation_alias=AliasChoices("FRONTEND_URL", "CORS_FRONTEND_URL"),
    )

    jwt_secret: str = Field(
        default="change-me-in-production",
        description="Clave para firmar tokens JWT. Define JWT_SECRET en .env en producción.",
    )
    jwt_algorithm: str = Field(default="HS256")
    jwt_expires_minutes: int = Field(default=60 * 24, description="Duración del access token en minutos")

    smtp_host: str = Field(default="", description="Servidor SMTP (vacío = envío deshabilitado hasta configurar)")
    smtp_port: int = Field(default=587)
    smtp_user: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_from: str = Field(default="", description='Remitente "From" (ej. nombre <correo@dominio.com>)')
    smtp_use_tls: bool = Field(default=True, description="STARTTLS en puerto 587")
    smtp_use_ssl: bool = Field(default=False, description="SMTP_SSL directo (p. ej. puerto 465)")

    whatsapp_access_token: str = Field(
        default="",
        description="Token de la app Meta (Graph API). Vacío = envío WhatsApp deshabilitado.",
    )
    whatsapp_phone_number_id: str = Field(
        default="",
        description="ID del número de WhatsApp Business en Graph (ruta .../PHONE_NUMBER_ID/messages).",
    )
    whatsapp_business_account_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "WHATSAPP_BUSINESS_ACCOUNT_ID",
            "WABA_ID",
            "WHATSAPP_WABA_ID",
        ),
        description="ID de la cuenta WhatsApp Business (WABA) en Graph; necesario para crear plantillas.",
    )
    whatsapp_graph_api_version: str = Field(
        default="v25.0",
        description="Versión de la Graph API (ej. v25.0).",
    )
    whatsapp_webhook_verify_token: str = Field(
        default="",
        description="Token de verificación del webhook (hub.verify_token en Meta). Vacío = GET falla.",
    )
    whatsapp_app_secret: str = Field(
        default="",
        description="App Secret de Meta; si está definido, se valida X-Hub-Signature-256 en POST.",
    )
    whatsapp_customer_care_window_hours: int = Field(
        default=24,
        ge=1,
        le=168,
        description="Horas desde el último mensaje entrante de WhatsApp del cliente para permitir texto de sesión (sin plantilla). Meta usa 24 h.",
    )

    public_api_base_url: str = Field(
        default="",
        description="URL base pública del API en HTTPS (sin barra final), p. ej. https://api.tudominio.com. "
        "Necesaria para plantillas con imagen en cabecera: Meta descarga la imagen desde esta URL + /api/public/...",
    )

    celery_broker_url: str = Field(
        default="",
        description="Broker Redis para Celery (ej. redis://127.0.0.1:6379/0). Vacío = no se encolan envíos programados.",
    )
    celery_result_backend: str = Field(
        default="",
        description="Backend de resultados Celery (ej. redis://127.0.0.1:6379/1). Vacío = mismo host que broker o deshabilitado según Celery.",
    )

    gcs_bucket: str = Field(
        default="",
        description="Bucket de Google Cloud Storage para archivos de importación. Vacío = almacenamiento local temporal (solo desarrollo).",
    )
    gcs_import_prefix: str = Field(
        default="imports",
        description="Prefijo de objetos GCS para imports (ej. imports/margesi/...).",
    )
    gcs_item_photos_prefix: str = Field(
        default="item-photos",
        description="Prefijo GCS para fotos de bienes en hoja de captura.",
    )
    gcs_local_fotos_prefix: str = Field(
        default="local-fotos",
        validation_alias=AliasChoices("GCS_LOCAL_FOTOS"),
        description="Prefijo GCS para fotos de locales (Reporte Locales).",
    )
    gcs_local_pdf_prefix: str = Field(
        default="local-pdf",
        validation_alias=AliasChoices("GCS_LOCAL_PDF"),
        description="Prefijo GCS para PDF de locales (Reporte Locales).",
    )
    gcs_logos_prefix: str = Field(
        default="tenant-logos",
        validation_alias=AliasChoices("GCS_IMPORT_PREFIX_LOGOS", "GCS_LOGOS_PREFIX"),
        description="Prefijo GCS para logos de tenant (PDF ficha inventario). Ej. tenant-logos/{tenant_id}/logo.png",
    )
    gcs_export_prefix: str = Field(
        default="exports",
        validation_alias=AliasChoices("GCS_IMPORT_PREFIX_EXPORT", "GCS_EXPORT_PREFIX"),
        description="Prefijo GCS para exportaciones CSV (ej. exports/reporte_aptot/...).",
    )
    gcs_export_signed_url_ttl_minutes: int = Field(
        default=60,
        description="Minutos de validez de la URL firmada para descargar exportaciones desde GCS.",
    )
    google_application_credentials: str = Field(
        default="",
        validation_alias=AliasChoices(
            "GOOGLE_APPLICATION_CREDENTIALS",
            "GCS_CREDENTIALS_PATH",
        ),
        description="Ruta al JSON de cuenta de servicio GCS. Vacío = Application Default Credentials (Cloud Run).",
    )

    @property
    def seed_demo_user_requested(self) -> bool:
        return os.getenv("SEED_DEMO_USER", "").lower() in ("1", "true", "yes")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def clear_settings_cache() -> None:
    get_settings.cache_clear()
