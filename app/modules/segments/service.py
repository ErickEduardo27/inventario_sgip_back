from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.contacts.models import Contact
from app.modules.segments.models import Segment
from app.modules.segments.schemas import (
    SegmentCreate,
    SegmentCriteria,
    SegmentOut,
    SegmentUpdate,
)


class SegmentService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def _uuid_list(vals: Any) -> list[UUID]:
        if not vals:
            return []
        out: list[UUID] = []
        for v in vals:
            try:
                out.append(UUID(str(v)))
            except ValueError:
                continue
        return out

    def _apply_criteria(self, stmt, tenant_id: UUID, criteria: dict[str, Any] | SegmentCriteria | None):
        stmt = stmt.where(Contact.tenant_id == tenant_id, Contact.is_deleted.is_(False))
        if not criteria:
            return stmt
        if isinstance(criteria, SegmentCriteria):
            criteria = criteria.model_dump(mode="json")
        site_ids = self._uuid_list(criteria.get("site_ids"))
        if site_ids:
            stmt = stmt.where(Contact.site_id.in_(site_ids))
        area_ids = self._uuid_list(criteria.get("area_ids"))
        if area_ids:
            stmt = stmt.where(Contact.area_id.in_(area_ids))
        position_ids = self._uuid_list(criteria.get("position_ids"))
        if position_ids:
            stmt = stmt.where(Contact.position_id.in_(position_ids))
        if criteria.get("regions"):
            stmt = stmt.where(Contact.region.in_(criteria["regions"]))
        if criteria.get("statuses"):
            stmt = stmt.where(Contact.status.in_(criteria["statuses"]))
        return stmt

    def _count(self, tenant_id: UUID, criteria: dict[str, Any] | SegmentCriteria | None) -> int:
        stmt = self._apply_criteria(select(func.count(Contact.id)), tenant_id, criteria)
        return int(self.db.scalar(stmt) or 0)

    def list_segments(self, tenant_id: UUID) -> list[SegmentOut]:
        rows = list(
            self.db.scalars(
                select(Segment)
                .where(Segment.tenant_id == tenant_id, Segment.is_deleted.is_(False))
                .order_by(Segment.name)
            ).all()
        )
        result: list[SegmentOut] = []
        for s in rows:
            result.append(
                SegmentOut(
                    id=s.id,
                    tenant_id=s.tenant_id,
                    name=s.name,
                    description=s.description,
                    criteria=s.criteria or {},
                    status=s.status,
                    contact_count=self._count(tenant_id, s.criteria),
                    created_at=s.created_at,
                )
            )
        return result

    def get_segment(self, tenant_id: UUID, segment_id: UUID) -> Segment:
        s = self.db.scalar(
            select(Segment).where(
                Segment.id == segment_id,
                Segment.tenant_id == tenant_id,
                Segment.is_deleted.is_(False),
            )
        )
        if not s:
            raise AppError("Segmento no encontrado", 404)
        return s

    def get_segment_out(self, tenant_id: UUID, segment_id: UUID) -> SegmentOut:
        s = self.get_segment(tenant_id, segment_id)
        return SegmentOut(
            id=s.id,
            tenant_id=s.tenant_id,
            name=s.name,
            description=s.description,
            criteria=s.criteria or {},
            status=s.status,
            contact_count=self._count(tenant_id, s.criteria),
            created_at=s.created_at,
        )

    def create_segment(self, tenant_id: UUID, body: SegmentCreate) -> SegmentOut:
        s = Segment(
            tenant_id=tenant_id,
            name=body.name.strip(),
            description=(body.description or "").strip(),
            criteria=body.criteria.model_dump(mode="json"),
            status=body.status,
        )
        self.db.add(s)
        try:
            self.db.commit()
            self.db.refresh(s)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_segments_tenant_name" in str(e.orig).lower():
                raise AppError("Ya existe un segmento con ese nombre", 409) from e
            raise AppError("No se pudo crear el segmento", 400) from e
        return self.get_segment_out(tenant_id, s.id)

    def update_segment(self, tenant_id: UUID, segment_id: UUID, body: SegmentUpdate) -> SegmentOut:
        s = self.get_segment(tenant_id, segment_id)
        data = body.model_dump(exclude_unset=True)
        if "criteria" in data and data["criteria"] is not None:
            data["criteria"] = (
                data["criteria"].model_dump(mode="json")
                if isinstance(data["criteria"], SegmentCriteria)
                else data["criteria"]
            )
        for k, v in data.items():
            setattr(s, k, v)
        try:
            self.db.commit()
            self.db.refresh(s)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_segments_tenant_name" in str(e.orig).lower():
                raise AppError("Ya existe un segmento con ese nombre", 409) from e
            raise AppError("No se pudo actualizar el segmento", 400) from e
        return self.get_segment_out(tenant_id, segment_id)

    def delete_segment(self, tenant_id: UUID, segment_id: UUID) -> None:
        s = self.get_segment(tenant_id, segment_id)
        s.is_deleted = True
        self.db.commit()

    def preview_count(self, tenant_id: UUID, criteria: SegmentCriteria) -> int:
        return self._count(tenant_id, criteria)

    def count_segment_contacts(self, tenant_id: UUID, segment_id: UUID) -> int:
        s = self.get_segment(tenant_id, segment_id)
        return self._count(tenant_id, s.criteria)

    def list_contact_ids_for_segment(self, tenant_id: UUID, segment_id: UUID) -> list[UUID]:
        """Contactos que cumplen los criterios del segmento (orden estable, sin duplicados)."""
        s = self.get_segment(tenant_id, segment_id)
        stmt = select(Contact.id)
        stmt = self._apply_criteria(stmt, tenant_id, s.criteria)
        rows = list(self.db.scalars(stmt).all())
        return list(dict.fromkeys(rows))
