from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=8, max_length=128)
    status: str = Field(default="active", max_length=50)
    is_superadmin: bool = False
    role_ids: list[UUID] = Field(default_factory=list)
    num_ini: int | None = None
    num_fin: int | None = None
    num_act: int | None = None
    eti_ini: int | None = None
    eti_fin: int | None = None
    eti_act: int | None = None


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, min_length=3, max_length=200)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    status: str | None = Field(default=None, max_length=50)
    is_superadmin: bool | None = None
    role_ids: list[UUID] | None = None
    num_ini: int | None = None
    num_fin: int | None = None
    num_act: int | None = None
    eti_ini: int | None = None
    eti_fin: int | None = None
    eti_act: int | None = None


class UserOut(BaseModel):
    id: UUID
    tenant_id: UUID
    full_name: str
    email: str
    status: str
    last_access_at: datetime | None
    is_superadmin: bool
    role_ids: list[UUID] = Field(default_factory=list)
    num_ini: int | None = None
    num_fin: int | None = None
    num_act: int | None = None
    eti_ini: int | None = None
    eti_fin: int | None = None
    eti_act: int | None = None

    model_config = ConfigDict(from_attributes=True)


class PagedMeta(BaseModel):
    total: int
    page: int
    per_page: int
    pages: int


class PagedUserRows(BaseModel):
    data: list[UserOut]
    meta: PagedMeta


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    code: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    is_system: bool = False


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_system: bool | None = None


class RoleOut(BaseModel):
    id: UUID
    tenant_id: UUID | None
    name: str
    code: str
    description: str
    is_system: bool

    model_config = ConfigDict(from_attributes=True)


class ComponentPermissions(BaseModel):
    view: bool
    create: bool
    edit: bool
    delete: bool
    export: bool
    scope: str


class UserComponentOut(BaseModel):
    code: str
    name: str
    group_name: str
    route: str
    icon: str | None
    is_portal: bool
    order_index: int
    permissions: ComponentPermissions


class UIComponentOut(BaseModel):
    code: str
    name: str
    group_name: str
    route: str
    icon: str | None
    order_index: int

    model_config = ConfigDict(from_attributes=True)


class RolePermissionRow(BaseModel):
    component_code: str
    component_name: str
    group_name: str
    can_view: bool = False
    can_create: bool = False
    can_edit: bool = False
    can_delete: bool = False
    can_export: bool = False
    scope: str = "tenant"


class RolePermissionsWrite(BaseModel):
    permissions: list[RolePermissionRow]
