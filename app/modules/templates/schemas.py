from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TemplateBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="comunicado", max_length=60)
    body: str = Field(min_length=1)
    variables: list[str] = Field(default_factory=list)
    status: str = Field(default="activo", max_length=40)


class TemplateCreate(TemplateBase):
    """Al crear, la plantilla se envía siempre a Meta (misma petición)."""

    wa_meta_category: Literal["UTILITY", "MARKETING", "AUTHENTICATION"] = "UTILITY"
    wa_language: str = Field(default="es_ES", min_length=2, max_length=32)
    wa_header_format: Literal["NONE", "IMAGE"] = "NONE"
    wa_quick_reply_buttons: list[str] = Field(
        default_factory=list,
        description="Hasta 3 textos de botón QUICK_REPLY (máx. 25 caracteres c/u) para la plantilla en Meta.",
    )
    wa_header_image_base64: str | None = Field(
        default=None,
        max_length=4_500_000,
        description="Imagen JPEG/PNG/WebP en base64 o data URL (cabecera IMAGE; se guarda en BD).",
    )
    wa_header_image_mime: str | None = Field(default=None, max_length=80)

    @field_validator("wa_quick_reply_buttons", mode="before")
    @classmethod
    def _normalize_quick_replies(cls, v: Any) -> list[str]:
        if not v:
            return []
        if not isinstance(v, list):
            return []
        out: list[str] = []
        for x in v[:3]:
            t = str(x).strip()[:25]
            if t:
                out.append(t)
        return out


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: str | None = Field(default=None, max_length=60)
    body: str | None = Field(default=None, min_length=1)
    variables: list[str] | None = None
    status: str | None = Field(default=None, max_length=40)


class TemplateOut(TemplateBase):
    id: UUID
    tenant_id: UUID
    created_at: datetime
    wa_meta_name: str | None = None
    wa_language: str | None = None
    wa_meta_category: str | None = None
    wa_review_status: str | None = None
    wa_review_reason: str | None = None
    wa_submitted_at: datetime | None = None
    wa_graph_template_id: str | None = None
    wa_header_format: str | None = None
    wa_quick_reply_buttons: list[str] | None = None
    wa_header_image_available: bool = False

    model_config = ConfigDict(from_attributes=True)


def _parse_meta_datetime(value: Any) -> datetime | None:
    """Parse timestamps returned by Graph (ISO o unix)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    s = str(value).strip()
    if not s:
        return None
    if s.isdigit():
        return datetime.fromtimestamp(int(s), tz=timezone.utc)
    # p. ej. 2024-05-01T12:00:00+0000 → +00:00 para fromisoformat
    if re.search(r"[+-]\d{4}$", s) and not re.search(r"[+-]\d{2}:\d{2}$", s):
        s = f"{s[:-5]}{s[-5:-2]}:{s[-2:]}"
    if s.endswith("Z"):
        s = f"{s[:-1]}+00:00"
    try:
        dt = datetime.fromisoformat(s)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class TemplateSubmitMetaBody(BaseModel):
    meta_category: Literal["UTILITY", "MARKETING", "AUTHENTICATION"] = "UTILITY"
    language: str = Field(default="es_ES", min_length=2, max_length=32)


class MetaWabaTemplateRow(BaseModel):
    """Plantilla tal como figura en la cuenta WABA (Graph GET message_templates)."""

    graph_id: str = ""
    name: str = ""
    status: str = ""
    language: str = ""
    category: str = ""
    quality_score: str | None = None
    last_updated_time: datetime | None = None

    @classmethod
    def from_graph(cls, item: dict[str, Any]) -> MetaWabaTemplateRow:
        qs = item.get("quality_score")
        if qs is None or qs == "":
            qss = None
        elif isinstance(qs, (str, int, float, bool)):
            qss = str(qs)
        else:
            qss = str(qs)[:200]
        return cls(
            graph_id=str(item.get("id") or "").strip(),
            name=str(item.get("name") or "").strip(),
            status=str(item.get("status") or "").strip(),
            language=str(item.get("language") or "").strip(),
            category=str(item.get("category") or "").strip(),
            quality_score=qss,
            last_updated_time=_parse_meta_datetime(item.get("last_updated_time")),
        )
