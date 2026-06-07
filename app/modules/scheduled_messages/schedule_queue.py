"""Encolar / revocar envíos programados en Celery (Redis como broker)."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.modules.scheduled_messages.models import ScheduledMessage
from app.modules.tenants.models import Tenant

logger = logging.getLogger(__name__)


def _tenant_timezone(db: Session, tenant_id: UUID) -> str:
    t = db.scalar(select(Tenant).where(Tenant.id == tenant_id))
    if t and (t.timezone or "").strip():
        return t.timezone.strip()
    return "America/Lima"


def compute_eta_utc(db: Session, sm: ScheduledMessage) -> datetime:
    from zoneinfo import ZoneInfo

    if sm.scheduled_date and sm.scheduled_time:
        tz_name = _tenant_timezone(db, sm.tenant_id)
        local = datetime.combine(sm.scheduled_date, sm.scheduled_time, tzinfo=ZoneInfo(tz_name))
        return local.astimezone(timezone.utc)
    return datetime.now(timezone.utc) + timedelta(minutes=1)


def revoke_dispatch_task(task_id: str | None) -> None:
    if not task_id or not (get_settings().celery_broker_url or "").strip():
        return
    try:
        from celery.result import AsyncResult

        from app.celery_app import celery_app

        AsyncResult(task_id, app=celery_app).revoke(terminate=True)
    except Exception as e:
        logger.warning("No se pudo revocar tarea Celery %s: %s", task_id, e)


def bind_dispatch_task(db: Session, sm: ScheduledMessage) -> None:
    """Programa la tarea en Redis para la fecha/hora del envío (timezone del tenant)."""
    if not (get_settings().celery_broker_url or "").strip():
        return
    revoke_dispatch_task(sm.celery_task_id)
    try:
        from app.tasks.scheduled_dispatch import dispatch_scheduled_message

        eta = compute_eta_utc(db, sm)
        now = datetime.now(timezone.utc)
        if eta <= now:
            eta = now + timedelta(seconds=10)
        res = dispatch_scheduled_message.apply_async(args=[str(sm.id)], eta=eta)
        sm.celery_task_id = res.id
        db.flush()
    except Exception:
        logger.exception("Encolado Celery falló para scheduled_message %s", sm.id)
