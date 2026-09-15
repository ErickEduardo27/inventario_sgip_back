"""Esquemas del API móvil de brigadas (captura offline + conciliación)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class MobileIdentifyRequest(BaseModel):
    ocr_text: str | None = None
    description: str | None = None
    marca: str | None = None
    modelo: str | None = None
    scanned_code: str | None = None
    environment_id: int | None = None
    establishment_id: int | None = None
    person_id: int | None = None
    labels: list[str] = Field(default_factory=list)
    limit: int = Field(default=8, ge=1, le=20)


class MobileSyncPhoto(BaseModel):
    slot: int = Field(default=1, ge=1, le=3)
    filename: str = "foto.jpg"
    content_base64: str


class MobileSyncItem(BaseModel):
    client_id: str
    card_id: int | None = None
    id_ambiente: int | None = None
    id_ccosto: int | None = None
    id_usuario: int | None = None
    scanned_code: str | None = None
    scan_tipo: str | None = None
    id_margesi: int | None = None
    no_conciliar: bool = False
    inv_num: int | str | None = None
    inv_num_1: str | None = None
    inv_num_2: str | None = None
    mar_num: str | None = None
    mar_cpat: str | None = None
    mar_des: str | None = None
    mar_mar: str | None = None
    mar_mod: str | None = None
    mar_ser: str | None = None
    mar_est: str | None = None
    mar_obs: str | None = None
    mar_col: str | None = None
    mar_med: str | None = None
    mar_esp: str | None = None
    mar_uso: str | None = None
    mar_seg: str | None = None
    mar_tip: str | None = None
    mar_ano: str | None = None
    mar_npla: str | None = None
    mar_nmot: str | None = None
    mar_ncha: str | None = None
    mar_eti: str | None = None
    mar_npri: str | None = None
    mar_ccat: str | None = None
    mar_foto: str | None = None
    mar_foto2: str | None = None
    mar_foto3: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    accuracy_m: float | None = None
    captured_at: str | None = None
    ai_label: str | None = None
    ai_confidence: float | None = None
    photos: list[MobileSyncPhoto] = Field(default_factory=list)


class MobileSyncRequest(BaseModel):
    items: list[MobileSyncItem] = Field(default_factory=list, max_length=80)


class MobileEnsureCardRequest(BaseModel):
    id_ambiente: int
    id_ccosto: int
    id_usuario: int | None = None
    nota_interna: str | None = None


class MobileLocationPing(BaseModel):
    establishment_id: int
    latitude: float
    longitude: float
    accuracy_m: float | None = None
    session_id: int | None = None
