from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_email(v: str) -> str:
    v = v.strip().lower()
    if "@" not in v or len(v.split("@")) != 2:
        raise ValueError("Correo electrónico no válido")
    local, domain = v.split("@")
    if not local or not domain or "." not in domain:
        raise ValueError("Correo electrónico no válido")
    return v


class ContactBase(BaseModel):
    first_name: str = Field(min_length=1, max_length=150)
    last_name: str = Field(default="", max_length=150)
    whatsapp_number: str = Field(min_length=5, max_length=50)
    document: str | None = Field(default=None, max_length=50)
    site_id: UUID | None = None
    area_id: UUID | None = None
    position_id: UUID | None = None
    region: str | None = Field(default=None, max_length=120)
    status: str = Field(default="activo", max_length=40)
    note: str | None = Field(default=None, max_length=500)
    email: str | None = Field(default=None, max_length=254)


class ContactCreate(ContactBase):
    email: str = Field(min_length=5, max_length=254)

    @field_validator("email")
    @classmethod
    def validate_email_required(cls, v: str) -> str:
        return _normalize_email(v)


class ContactUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=150)
    last_name: str | None = Field(default=None, max_length=150)
    whatsapp_number: str | None = Field(default=None, min_length=5, max_length=50)
    document: str | None = Field(default=None, max_length=50)
    site_id: UUID | None = None
    area_id: UUID | None = None
    position_id: UUID | None = None
    region: str | None = Field(default=None, max_length=120)
    status: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=500)
    email: str | None = Field(default=None, max_length=254)

    @field_validator("email")
    @classmethod
    def validate_email_optional(cls, v: str | None) -> str | None:
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        return _normalize_email(str(v))


class ContactOut(ContactBase):
    id: UUID
    tenant_id: UUID
    created_at: datetime
    site_name: str | None = None
    area_name: str | None = None
    position_name: str | None = None

    model_config = ConfigDict(from_attributes=True)


class ContactSummary(BaseModel):
    total: int
    activos: int
    inactivos: int
    observados: int
    invalidos: int
