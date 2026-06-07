from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.campaigns.models import Campaign, CampaignSegment, CampaignTemplate
from app.modules.iam.models import User
from app.modules.scheduled_messages.models import (
    ScheduledMessage,
    ScheduledMessageContact,
    ScheduledMessageSegment,
)
from app.modules.scheduled_messages.schedule_queue import bind_dispatch_task, revoke_dispatch_task
from app.modules.scheduled_messages.schemas import (
    ScheduledMessageCreate,
    ScheduledMessageOut,
    ScheduledMessageSchedule,
    ScheduledMessageUpdate,
)
from app.modules.segments.models import Segment
from app.modules.segments.service import SegmentService
from app.modules.templates.models import MessageTemplate


class ScheduledMessageService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _campaign_name(self, campaign_id: UUID) -> str:
        name = self.db.scalar(select(Campaign.name).where(Campaign.id == campaign_id))
        return name or ""

    def _segment_names(self, scheduled_message_id: UUID) -> list[str]:
        rows = self.db.execute(
            select(Segment.name)
            .join(ScheduledMessageSegment, ScheduledMessageSegment.segment_id == Segment.id)
            .where(ScheduledMessageSegment.scheduled_message_id == scheduled_message_id)
            .order_by(Segment.name)
        ).all()
        return [r[0] for r in rows]

    def _segment_ids(self, scheduled_message_id: UUID) -> list[UUID]:
        rows = self.db.scalars(
            select(ScheduledMessageSegment.segment_id).where(
                ScheduledMessageSegment.scheduled_message_id == scheduled_message_id
            )
        ).all()
        return list(rows)

    def _resolve_sm_contacts_count(self, tenant_id: UUID, sm: ScheduledMessage) -> int:
        seg_svc = SegmentService(self.db)
        total = 0
        seg_rows = self.db.scalars(
            select(ScheduledMessageSegment.segment_id).where(
                ScheduledMessageSegment.scheduled_message_id == sm.id
            )
        ).all()
        for sid in seg_rows:
            total += seg_svc.count_segment_contacts(tenant_id, sid)
        n_direct = self.db.scalar(
            select(func.count())
            .select_from(ScheduledMessageContact)
            .where(ScheduledMessageContact.scheduled_message_id == sm.id)
        )
        return total + int(n_direct or 0)

    def _sync_sm_segments_from_campaign(self, scheduled_message_id: UUID, campaign_id: UUID) -> None:
        self.db.execute(
            delete(ScheduledMessageSegment).where(
                ScheduledMessageSegment.scheduled_message_id == scheduled_message_id
            )
        )
        self.db.flush()
        raw_ids = [
            cs.segment_id
            for cs in self.db.scalars(select(CampaignSegment).where(CampaignSegment.campaign_id == campaign_id))
        ]
        for sid in dict.fromkeys(raw_ids):
            self.db.add(
                ScheduledMessageSegment(scheduled_message_id=scheduled_message_id, segment_id=sid)
            )

    def _compute_contacts_from_segment_ids(self, tenant_id: UUID, segment_ids: list[UUID]) -> int:
        seg_svc = SegmentService(self.db)
        total = 0
        for sid in segment_ids:
            total += seg_svc.count_segment_contacts(tenant_id, sid)
        return total

    def _resolve_template_id(
        self, tenant_id: UUID, campaign_id: UUID, requested: UUID | None
    ) -> UUID | None:
        if requested is not None:
            ct = self.db.scalar(
                select(CampaignTemplate).where(
                    CampaignTemplate.campaign_id == campaign_id,
                    CampaignTemplate.template_id == requested,
                )
            )
            if not ct:
                raise AppError("La plantilla seleccionada no está asociada a esta campaña", 400)
            tpl = self.db.scalar(
                select(MessageTemplate).where(
                    MessageTemplate.id == requested,
                    MessageTemplate.tenant_id == tenant_id,
                    MessageTemplate.is_deleted.is_(False),
                )
            )
            if not tpl:
                raise AppError("Plantilla no encontrada", 404)
            return requested
        return self.db.scalar(
            select(CampaignTemplate.template_id).where(CampaignTemplate.campaign_id == campaign_id).limit(1)
        )

    def create_scheduled_message(
        self, tenant_id: UUID, user_id: UUID, body: ScheduledMessageCreate
    ) -> ScheduledMessageOut:
        camp = self.db.scalar(
            select(Campaign).where(
                Campaign.id == body.campaign_id,
                Campaign.tenant_id == tenant_id,
                Campaign.is_deleted.is_(False),
            )
        )
        if not camp:
            raise AppError("Campaña no encontrada", 404)
        if camp.status != "activo":
            raise AppError("Solo se pueden programar envíos en campañas activas", 400)

        tpl_id = self._resolve_template_id(tenant_id, camp.id, body.template_id)

        dn = (body.display_name or "").strip() or None
        sm = ScheduledMessage(
            tenant_id=tenant_id,
            campaign_id=camp.id,
            display_name=dn,
            template_id=tpl_id,
            contenido_final=body.contenido_final,
            scheduled_date=body.scheduled_date,
            scheduled_time=body.scheduled_time,
            status="programado",
            created_by_user_id=user_id,
        )
        self.db.add(sm)
        self.db.flush()

        if body.segment_ids:
            for sid in dict.fromkeys(body.segment_ids):
                self.db.add(ScheduledMessageSegment(scheduled_message_id=sm.id, segment_id=sid))
        else:
            self._sync_sm_segments_from_campaign(sm.id, camp.id)

        seg_ids = list(
            dict.fromkeys(
                [
                    cs.segment_id
                    for cs in self.db.scalars(
                        select(CampaignSegment).where(CampaignSegment.campaign_id == camp.id)
                    )
                ]
            )
        )
        camp.contacts_count = self._compute_contacts_from_segment_ids(tenant_id, seg_ids)
        if sm.status == "programado":
            bind_dispatch_task(self.db, sm)
        self.db.commit()
        self.db.refresh(sm)
        return self._to_out(sm)

    def _to_out(self, sm: ScheduledMessage) -> ScheduledMessageOut:
        tpl_name = None
        if sm.template_id:
            tpl_name = self.db.scalar(select(MessageTemplate.name).where(MessageTemplate.id == sm.template_id))
        creator_name = None
        if sm.created_by_user_id:
            creator_name = self.db.scalar(select(User.full_name).where(User.id == sm.created_by_user_id))
        cc = self._resolve_sm_contacts_count(sm.tenant_id, sm)
        camp = self.db.scalar(select(Campaign).where(Campaign.id == sm.campaign_id))
        return ScheduledMessageOut(
            id=sm.id,
            tenant_id=sm.tenant_id,
            campaign_id=sm.campaign_id,
            display_name=sm.display_name,
            campaign_name=self._campaign_name(sm.campaign_id),
            campaign_type=camp.campaign_type if camp else "comunicado",
            campaign_description=camp.description if camp else "",
            template_id=sm.template_id,
            template_name=tpl_name,
            contenido_final=sm.contenido_final,
            scheduled_date=sm.scheduled_date,
            scheduled_time=sm.scheduled_time,
            status=sm.status,
            segment_ids=self._segment_ids(sm.id),
            segment_names=self._segment_names(sm.id),
            contacts_count=cc,
            created_at=sm.created_at,
            created_by_user_id=sm.created_by_user_id,
            created_by_name=creator_name,
        )

    def get_scheduled_message_out(self, tenant_id: UUID, scheduled_message_id: UUID) -> ScheduledMessageOut:
        sm = self.get_scheduled_message(tenant_id, scheduled_message_id)
        return self._to_out(sm)

    def get_scheduled_message(self, tenant_id: UUID, scheduled_message_id: UUID) -> ScheduledMessage:
        sm = self.db.scalar(
            select(ScheduledMessage).where(
                ScheduledMessage.id == scheduled_message_id,
                ScheduledMessage.tenant_id == tenant_id,
                ScheduledMessage.is_deleted.is_(False),
            )
        )
        if not sm:
            raise AppError("Mensaje programado no encontrado", 404)
        return sm

    def list_scheduled_messages(
        self,
        tenant_id: UUID,
        *,
        statuses: list[str] | None = None,
    ) -> list[ScheduledMessageOut]:
        if statuses is None:
            statuses = ["borrador", "programado", "en_cola", "enviando"]
        stmt = (
            select(ScheduledMessage)
            .where(
                ScheduledMessage.tenant_id == tenant_id,
                ScheduledMessage.is_deleted.is_(False),
                ScheduledMessage.status.in_(statuses),
            )
            .order_by(ScheduledMessage.created_at.desc())
        )
        rows = list(self.db.scalars(stmt).all())
        return [self._to_out(sm) for sm in rows]

    def update_scheduled_message(
        self, tenant_id: UUID, scheduled_message_id: UUID, body: ScheduledMessageUpdate
    ) -> ScheduledMessageOut:
        sm = self.get_scheduled_message(tenant_id, scheduled_message_id)
        data = body.model_dump(exclude_unset=True)
        if "display_name" in data:
            raw = data["display_name"]
            if raw is None:
                data["display_name"] = None
            else:
                data["display_name"] = (raw or "").strip() or None
        seg_ids = data.pop("segment_ids", None)
        contact_ids = data.pop("contact_ids", None)
        if "template_id" in data:
            raw_tid = data.pop("template_id")
            data["template_id"] = self._resolve_template_id(tenant_id, sm.campaign_id, raw_tid)
        for k, v in data.items():
            setattr(sm, k, v)
        if seg_ids is not None:
            self.db.execute(delete(ScheduledMessageSegment).where(ScheduledMessageSegment.scheduled_message_id == sm.id))
            for sid in dict.fromkeys(seg_ids):
                self.db.add(ScheduledMessageSegment(scheduled_message_id=sm.id, segment_id=sid))
        if contact_ids is not None:
            self.db.execute(delete(ScheduledMessageContact).where(ScheduledMessageContact.scheduled_message_id == sm.id))
            for cid in dict.fromkeys(contact_ids):
                self.db.add(ScheduledMessageContact(scheduled_message_id=sm.id, contact_id=cid))
        if sm.status == "programado":
            bind_dispatch_task(self.db, sm)
        self.db.commit()
        self.db.refresh(sm)
        return self._to_out(sm)

    def reschedule(self, tenant_id: UUID, scheduled_message_id: UUID, body: ScheduledMessageSchedule) -> ScheduledMessageOut:
        sm = self.get_scheduled_message(tenant_id, scheduled_message_id)
        sm.scheduled_date = body.scheduled_date
        sm.scheduled_time = body.scheduled_time
        sm.status = "programado"
        bind_dispatch_task(self.db, sm)
        self.db.commit()
        self.db.refresh(sm)
        return self._to_out(sm)

    def cancel_scheduled_message(self, tenant_id: UUID, scheduled_message_id: UUID) -> ScheduledMessageOut:
        sm = self.get_scheduled_message(tenant_id, scheduled_message_id)
        if sm.status in ("enviado", "fallido"):
            raise AppError("Este envío ya fue procesado y no se puede cancelar", 400)
        revoke_dispatch_task(sm.celery_task_id)
        sm.celery_task_id = None
        sm.status = "cancelado"
        self.db.commit()
        self.db.refresh(sm)
        return self._to_out(sm)

    def delete_scheduled_message(self, tenant_id: UUID, scheduled_message_id: UUID) -> None:
        sm = self.get_scheduled_message(tenant_id, scheduled_message_id)
        revoke_dispatch_task(sm.celery_task_id)
        sm.is_deleted = True
        self.db.commit()
