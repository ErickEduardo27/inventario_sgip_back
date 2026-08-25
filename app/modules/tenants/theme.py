"""Theme Engine: tokens de marca por tenant (colores, tipografía, textos)."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

HEX_RE = re.compile(r"^#([0-9a-fA-F]{6})$")
FONT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 \-]{0,78}$")

DEFAULT_PRIMARY_HEX = "#2474F5"
DEFAULT_ACCENT_HEX = "#22998A"
DEFAULT_BACKGROUND_HEX = "#FAF8F8"
DEFAULT_APP_NAME = "Inventario SAP 2026"
DEFAULT_LOGIN_SUBTITLE = "Sistema de Administración Patrimonial"
DEFAULT_FONT = "Inter"
DEFAULT_RADIUS = "0.625rem"


class TenantTheme(BaseModel):
    """Configuración visual pública del portal (white-label)."""

    app_name: str = Field(default=DEFAULT_APP_NAME, max_length=80)
    login_subtitle: str = Field(default=DEFAULT_LOGIN_SUBTITLE, max_length=160)
    primary_hex: str = Field(default=DEFAULT_PRIMARY_HEX, max_length=7)
    accent_hex: str = Field(default=DEFAULT_ACCENT_HEX, max_length=7)
    background_hex: str = Field(default=DEFAULT_BACKGROUND_HEX, max_length=7)
    font_family: str = Field(default=DEFAULT_FONT, max_length=80)
    favicon_url: str | None = Field(default=None, max_length=500)
    radius: str = Field(default=DEFAULT_RADIUS, max_length=24)

    @field_validator("primary_hex", "accent_hex", "background_hex")
    @classmethod
    def _hex(cls, v: str) -> str:
        raw = (v or "").strip()
        if not HEX_RE.match(raw):
            raise ValueError("Color debe ser hexadecimal #RRGGBB")
        return raw.upper()

    @field_validator("font_family")
    @classmethod
    def _font(cls, v: str) -> str:
        raw = (v or DEFAULT_FONT).strip()
        if not FONT_RE.match(raw):
            return DEFAULT_FONT
        return raw

    @field_validator("app_name")
    @classmethod
    def _app_name(cls, v: str) -> str:
        return (v or "").strip() or DEFAULT_APP_NAME

    @field_validator("login_subtitle")
    @classmethod
    def _subtitle(cls, v: str) -> str:
        return (v or "").strip() or DEFAULT_LOGIN_SUBTITLE


class TenantThemeOut(TenantTheme):
    logo_url: str | None = None


def parse_theme(raw: dict[str, Any] | None, *, logo_url: str | None = None) -> TenantThemeOut:
    data = dict(raw or {})
    try:
        theme = TenantTheme.model_validate(data)
    except Exception:
        theme = TenantTheme()
    return TenantThemeOut(**theme.model_dump(), logo_url=logo_url or None)


def primary_hex_openpyxl(tenant_id: UUID) -> str:
    """Color primario del tenant sin ``#`` (formato openpyxl)."""
    from uuid import UUID as UUID_t

    from app.db.session import SessionLocal
    from app.modules.settings.service import SettingsService

    tid = tenant_id if isinstance(tenant_id, UUID_t) else UUID_t(str(tenant_id))
    with SessionLocal() as db:
        settings = SettingsService(db).get_settings(tid)
        theme = parse_theme(settings.portal_branding, logo_url=settings.logo_url)
        return theme.primary_hex.lstrip("#").upper()


def merge_theme(current: dict[str, Any] | None, incoming: dict[str, Any] | None) -> dict[str, Any]:
    base = parse_theme(current).model_dump(exclude={"logo_url"})
    if not incoming:
        return base
    patched = {**base, **{k: v for k, v in incoming.items() if v is not None}}
    return TenantTheme.model_validate(patched).model_dump()
