"""Envío de mensajes programados: worker Celery → WhatsApp Cloud API."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select

from app.celery_app import celery_app
from app.core.exceptions import AppError
from app.db.session import SessionLocal
from app.modules.omnichannel.schemas import SendWhatsAppTemplateBody
from app.modules.omnichannel.service import OmnichannelService
from app.modules.scheduled_messages.models import (
    ScheduledMessage,
    ScheduledMessageContact,
    ScheduledMessageSegment,
)
from app.modules.segments.service import SegmentService

logger = logging.getLogger(__name__)


@celery_app.task(name="scheduled_messages.dispatch_scheduled")
def dispatch_scheduled_message(scheduled_message_id: str) -> None:
    sm_uuid = UUID(scheduled_message_id)
    db = SessionLocal()
    try:
        sm = db.scalar(
            select(ScheduledMessage).where(
                ScheduledMessage.id == sm_uuid,
                ScheduledMessage.is_deleted.is_(False),
            )
        )
        if not sm:
            logger.warning("dispatch: scheduled_message no encontrado %s", scheduled_message_id)
            return
        if sm.status not in ("programado", "en_cola"):
            logger.info("dispatch omitido %s status=%s", sm_uuid, sm.status)
            return
        if not sm.template_id:
            sm.status = "fallido"
            sm.celery_task_id = None
            db.commit()
            logger.warning("dispatch: sin plantilla %s", sm_uuid)
            return

        sm.status = "enviando"
        db.commit()

        seg_ids = list(
            db.scalars(
                select(ScheduledMessageSegment.segment_id).where(
                    ScheduledMessageSegment.scheduled_message_id == sm.id
                )
            ).all()
        )
        direct_ids = list(
            db.scalars(
                select(ScheduledMessageContact.contact_id).where(
                    ScheduledMessageContact.scheduled_message_id == sm.id
                )
            ).all()
        )

        seen: set[UUID] = set()
        contact_ids: list[UUID] = []
        seg_svc = SegmentService(db)
        for sid in seg_ids:
            for cid in seg_svc.list_contact_ids_for_segment(sm.tenant_id, sid):
                if cid not in seen:
                    seen.add(cid)
                    contact_ids.append(cid)
        for cid in direct_ids:
            if cid not in seen:
                seen.add(cid)
                contact_ids.append(cid)

        if not contact_ids:
            sm_live = db.get(ScheduledMessage, sm_uuid)
            if sm_live:
                sm_live.status = "fallido"
                sm_live.celery_task_id = None
                db.commit()
            logger.warning("dispatch: sin contactos %s", sm_uuid)
            return

        omni = OmnichannelService(db)
        ok = 0
        for cid in contact_ids:
            try:
                omni.send_whatsapp_template(
                    sm.tenant_id,
                    cid,
                    SendWhatsAppTemplateBody(template_id=sm.template_id),
                )
                ok += 1
            except AppError as e:
                logger.warning("WhatsApp AppError sm=%s contact=%s: %s", sm_uuid, cid, e.message)
            except Exception as e:
                logger.warning("WhatsApp error sm=%s contact=%s: %s", sm_uuid, cid, e)

        sm_live = db.get(ScheduledMessage, sm_uuid)
        if sm_live:
            sm_live.status = "enviado" if ok > 0 else "fallido"
            sm_live.celery_task_id = None
            db.commit()
    except Exception:
        logger.exception("dispatch_scheduled_message error %s", scheduled_message_id)
        try:
            sm2 = db.scalar(select(ScheduledMessage).where(ScheduledMessage.id == sm_uuid))
            if sm2:
                sm2.status = "fallido"
                sm2.celery_task_id = None
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()
