"""Esquemas Pydantic para asistencia."""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AttendanceGeofencePreview(BaseModel):
    establishment_id: int
    latitude: float
    longitude: float


class AttendanceMarkWrite(BaseModel):
    establishment_id: int
    mark_type: str = Field(..., description="entrada | inicio_inventario | pausa | regreso | fin_jornada")
    latitude: float
    longitude: float
    accuracy_m: float | None = None
    device_info: str | None = None


class AttendanceLocationSampleWrite(BaseModel):
    session_id: int
    latitude: float
    longitude: float
    accuracy_m: float | None = None


class AttendanceAssignmentsWrite(BaseModel):
    user_id: UUID
    establishment_ids: list[int] = Field(default_factory=list)


class AttendancePanelFilters(BaseModel):
    work_date: date | None = None
    user_id: UUID | None = None
    establishment_id: int | None = None
    page: int = 1
    per_page: int = 20


class AttendanceSessionListResponse(BaseModel):
    data: list[dict[str, Any]]
    meta: dict[str, Any]
