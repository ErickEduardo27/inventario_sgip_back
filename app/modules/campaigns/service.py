from datetime import date, time
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.campaigns.models import Campaign, CampaignSegment, CampaignTemplate
from app.modules.campaigns.schemas import (
    CampaignCreate,
    CampaignOut,
    CampaignSchedule,
    CampaignUpdate,
)
from app.modules.iam.models import User
from app.modules.scheduled_messages.models import (
    ScheduledMessage,
    ScheduledMessageContact,
    ScheduledMessageSegment,
)
from app.modules.scheduled_messages.schedule_queue import bind_dispatch_task, revoke_dispatch_task
from app.modules.segments.models import Segment
from app.modules.segments.service import SegmentService
from app.modules.templates.models import MessageTemplate


class CampaignService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _junction_segment_meta(self, campaign_id: UUID) -> tuple[list[UUID], list[str]]:
        rows = self.db.execute(
            select(CampaignSegment.segment_id, Segment.name)
            .join(Segment, Segment.id == CampaignSegment.segment_id)
            .where(CampaignSegment.campaign_id == campaign_id)
            .order_by(Segment.name)
        ).all()
        seen: set[UUID] = set()
        seg_ids: list[UUID] = []
        seg_names: list[str] = []
        for sid, name in rows:
            if sid in seen:
                continue
            seen.add(sid)
            seg_ids.append(sid)
            seg_names.append(name)
        return seg_ids, seg_names

    def _junction_template_meta(self, campaign_id: UUID) -> tuple[list[UUID], list[str]]:
        rows = self.db.execute(
            select(CampaignTemplate.template_id, MessageTemplate.name)
            .join(MessageTemplate, MessageTemplate.id == CampaignTemplate.template_id)
            .where(CampaignTemplate.campaign_id == campaign_id)
            .order_by(MessageTemplate.name)
        ).all()
        seen: set[UUID] = set()
        tpl_ids: list[UUID] = []
        tpl_names: list[str] = []
        for tid, name in rows:
            if tid in seen:
                continue
            seen.add(tid)
            tpl_ids.append(tid)
            tpl_names.append(name)
        return tpl_ids, tpl_names

    def _next_schedule(self, campaign_id: UUID) -> tuple[date | None, time | None]:
        row = self.db.execute(
            select(ScheduledMessage.scheduled_date, ScheduledMessage.scheduled_time)
            .where(
                ScheduledMessage.campaign_id == campaign_id,
                ScheduledMessage.is_deleted.is_(False),
                ScheduledMessage.scheduled_date.isnot(None),
            )
            .order_by(ScheduledMessage.scheduled_date, ScheduledMessage.scheduled_time)
            .limit(1)
        ).first()
        if not row:
            return None, None
        return row[0], row[1]

    def _compute_contacts_count(self, tenant_id: UUID, segment_ids: list[UUID]) -> int:
        seg_svc = SegmentService(self.db)
        total = 0
        for sid in segment_ids:
            total += seg_svc.count_segment_contacts(tenant_id, sid)
        return total

    def _sync_campaign_segments(self, campaign_id: UUID, segment_ids: list[UUID]) -> None:
        unique_ids = list(dict.fromkeys(segment_ids))
        self.db.execute(delete(CampaignSegment).where(CampaignSegment.campaign_id == campaign_id))
        for sid in unique_ids:
            self.db.add(CampaignSegment(campaign_id=campaign_id, segment_id=sid))

    def _sync_campaign_templates(self, campaign_id: UUID, template_ids: list[UUID]) -> None:
        unique_ids = list(dict.fromkeys(template_ids))
        self.db.execute(delete(CampaignTemplate).where(CampaignTemplate.campaign_id == campaign_id))
        for tid in unique_ids:
            self.db.add(CampaignTemplate(campaign_id=campaign_id, template_id=tid))

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

    def _get_or_create_primary_scheduled_message(
        self, tenant_id: UUID, campaign_id: UUID, user_id: UUID
    ) -> ScheduledMessage:
        sm = self.db.scalar(
            select(ScheduledMessage)
            .where(
                ScheduledMessage.campaign_id == campaign_id,
                ScheduledMessage.tenant_id == tenant_id,
                ScheduledMessage.is_deleted.is_(False),
            )
            .order_by(ScheduledMessage.created_at.asc())
            .limit(1)
        )
        if sm:
            return sm
        tpl_id = self.db.scalar(
            select(CampaignTemplate.template_id)
            .where(CampaignTemplate.campaign_id == campaign_id)
            .limit(1)
        )
        sm = ScheduledMessage(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            template_id=tpl_id,
            status="borrador",
            created_by_user_id=user_id,
        )
        self.db.add(sm)
        self.db.flush()
        return sm

    def _to_out(self, c: Campaign) -> CampaignOut:
        seg_ids, seg_names = self._junction_segment_meta(c.id)
        tpl_ids, tpl_names = self._junction_template_meta(c.id)
        nd, nt = self._next_schedule(c.id)
        creator_name = None
        if c.created_by_user_id:
            creator_name = self.db.scalar(select(User.full_name).where(User.id == c.created_by_user_id))
        return CampaignOut(
            id=c.id,
            tenant_id=c.tenant_id,
            name=c.name,
            description=c.description,
            campaign_type=c.campaign_type,
            status=c.status,
            start_date=c.start_date,
            end_date=c.end_date,
            observation=c.observation,
            segment_ids=seg_ids,
            segment_names=seg_names,
            template_ids=tpl_ids,
            template_names=tpl_names,
            next_scheduled_date=nd,
            next_scheduled_time=nt,
            contacts_count=c.contacts_count,
            sent_count=c.sent_count,
            delivered_count=c.delivered_count,
            failed_count=c.failed_count,
            read_count=c.read_count,
            response_count=c.response_count,
            estimated_cost=float(c.estimated_cost or 0),
            sent_at=c.sent_at,
            finished_at=c.finished_at,
            created_at=c.created_at,
            created_by_user_id=c.created_by_user_id,
            created_by_name=creator_name,
        )

    def list_campaigns(
        self,
        tenant_id: UUID,
        *,
        statuses: list[str] | None = None,
    ) -> list[CampaignOut]:
        stmt = (
            select(Campaign)
            .where(Campaign.tenant_id == tenant_id, Campaign.is_deleted.is_(False))
            .order_by(Campaign.created_at.desc())
        )
        if statuses:
            stmt = stmt.where(Campaign.status.in_(statuses))
        rows = list(self.db.scalars(stmt).all())
        return [self._to_out(c) for c in rows]

    def get_campaign(self, tenant_id: UUID, campaign_id: UUID) -> Campaign:
        c = self.db.scalar(
            select(Campaign).where(
                Campaign.id == campaign_id,
                Campaign.tenant_id == tenant_id,
                Campaign.is_deleted.is_(False),
            )
        )
        if not c:
            raise AppError("Campaña no encontrada", 404)
        return c

    def get_campaign_out(self, tenant_id: UUID, campaign_id: UUID) -> CampaignOut:
        return self._to_out(self.get_campaign(tenant_id, campaign_id))

    def create_campaign(self, tenant_id: UUID, user_id: UUID, body: CampaignCreate) -> CampaignOut:
        segment_ids = list(dict.fromkeys(body.segment_ids))
        template_ids = list(dict.fromkeys(body.template_ids))
        contacts_count = self._compute_contacts_count(tenant_id, segment_ids)
        c = Campaign(
            tenant_id=tenant_id,
            name=body.name.strip(),
            description=(body.description or "").strip(),
            campaign_type=body.campaign_type,
            status=body.status,
            start_date=body.start_date,
            end_date=body.end_date,
            observation=(body.observation or "").strip() or None,
            contacts_count=contacts_count,
            created_by_user_id=user_id,
        )
        self.db.add(c)
        self.db.flush()
        self._sync_campaign_segments(c.id, segment_ids)
        self._sync_campaign_templates(c.id, template_ids)
        self.db.commit()
        self.db.refresh(c)
        return self._to_out(c)

    def update_campaign(self, tenant_id: UUID, campaign_id: UUID, body: CampaignUpdate) -> CampaignOut:
        c = self.get_campaign(tenant_id, campaign_id)
        data = body.model_dump(exclude_unset=True)
        segment_ids = data.pop("segment_ids", None)
        template_ids = data.pop("template_ids", None)
        for k, v in data.items():
            if k == "observation" and v is not None:
                v = str(v).strip() or None
            setattr(c, k, v)
        if segment_ids is not None:
            segment_ids = list(dict.fromkeys(segment_ids))
            self._sync_campaign_segments(c.id, segment_ids)
            c.contacts_count = self._compute_contacts_count(tenant_id, segment_ids)
        if template_ids is not None:
            template_ids = list(dict.fromkeys(template_ids))
            self._sync_campaign_templates(c.id, template_ids)
        self.db.commit()
        self.db.refresh(c)
        return self._to_out(c)

    def delete_campaign(self, tenant_id: UUID, campaign_id: UUID) -> None:
        c = self.get_campaign(tenant_id, campaign_id)
        c.is_deleted = True
        for sm in self.db.scalars(
            select(ScheduledMessage).where(ScheduledMessage.campaign_id == campaign_id)
        ):
            sm.is_deleted = True
        self.db.commit()

    def duplicate_campaign(self, tenant_id: UUID, campaign_id: UUID, user_id: UUID) -> CampaignOut:
        original = self.get_campaign(tenant_id, campaign_id)
        seg_ids, _ = self._junction_segment_meta(original.id)
        tpl_ids, _ = self._junction_template_meta(original.id)
        copy_c = Campaign(
            tenant_id=tenant_id,
            name=f"{original.name} (copia)",
            description=original.description,
            campaign_type=original.campaign_type,
            status="activo",
            start_date=original.start_date,
            end_date=original.end_date,
            observation=original.observation,
            contacts_count=original.contacts_count,
            created_by_user_id=user_id,
        )
        self.db.add(copy_c)
        self.db.flush()
        self._sync_campaign_segments(copy_c.id, seg_ids)
        self._sync_campaign_templates(copy_c.id, tpl_ids)
        for sm in self.db.scalars(
            select(ScheduledMessage).where(
                ScheduledMessage.campaign_id == original.id,
                ScheduledMessage.is_deleted.is_(False),
            )
        ):
            new_sm = ScheduledMessage(
                tenant_id=tenant_id,
                campaign_id=copy_c.id,
                template_id=sm.template_id,
                contenido_final=sm.contenido_final,
                scheduled_date=None,
                scheduled_time=None,
                status="borrador",
                created_by_user_id=user_id,
            )
            self.db.add(new_sm)
            self.db.flush()
            for sc in self.db.scalars(
                select(ScheduledMessageContact).where(
                    ScheduledMessageContact.scheduled_message_id == sm.id
                )
            ):
                self.db.add(
                    ScheduledMessageContact(scheduled_message_id=new_sm.id, contact_id=sc.contact_id)
                )
            seg_ids_sm = [
                ss.segment_id
                for ss in self.db.scalars(
                    select(ScheduledMessageSegment).where(
                        ScheduledMessageSegment.scheduled_message_id == sm.id
                    )
                )
            ]
            for sid in dict.fromkeys(seg_ids_sm):
                self.db.add(
                    ScheduledMessageSegment(scheduled_message_id=new_sm.id, segment_id=sid)
                )
        self.db.commit()
        self.db.refresh(copy_c)
        return self._to_out(copy_c)

    def schedule_campaign(
        self, tenant_id: UUID, campaign_id: UUID, body: CampaignSchedule, user_id: UUID
    ) -> CampaignOut:
        c = self.get_campaign(tenant_id, campaign_id)
        if c.status != "activo":
            raise AppError("Solo se pueden programar envíos en campañas activas", 400)
        sm = self._get_or_create_primary_scheduled_message(tenant_id, campaign_id, user_id)
        if sm.template_id is None:
            tpl_id = self.db.scalar(
                select(CampaignTemplate.template_id)
                .where(CampaignTemplate.campaign_id == campaign_id)
                .limit(1)
            )
            if tpl_id:
                sm.template_id = tpl_id
        sm.scheduled_date = body.scheduled_date
        sm.scheduled_time = body.scheduled_time
        sm.status = "programado"
        self._sync_sm_segments_from_campaign(sm.id, campaign_id)
        seg_ids, _ = self._junction_segment_meta(c.id)
        c.contacts_count = self._compute_contacts_count(tenant_id, seg_ids)
        bind_dispatch_task(self.db, sm)
        self.db.commit()
        self.db.refresh(c)
        return self._to_out(c)

    def cancel_campaign(self, tenant_id: UUID, campaign_id: UUID) -> CampaignOut:
        c = self.get_campaign(tenant_id, campaign_id)
        for sm in self.db.scalars(
            select(ScheduledMessage).where(
                ScheduledMessage.campaign_id == campaign_id,
                ScheduledMessage.tenant_id == tenant_id,
                ScheduledMessage.is_deleted.is_(False),
            )
        ):
            if sm.status not in ("enviado", "fallido"):
                revoke_dispatch_task(sm.celery_task_id)
                sm.celery_task_id = None
                sm.status = "cancelado"
        self.db.commit()
        self.db.refresh(c)
        return self._to_out(c)
