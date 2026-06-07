from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_id
from app.core.exceptions import AppError
from app.db.session import get_db
from app.modules.iam.models import User
from app.modules.scheduled_messages.schemas import (
    ScheduledMessageCreate,
    ScheduledMessageOut,
    ScheduledMessageSchedule,
    ScheduledMessageUpdate,
)
from app.modules.scheduled_messages.service import ScheduledMessageService

router = APIRouter()


def _handle(err: AppError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.message)


@router.get("", response_model=list[ScheduledMessageOut])
def list_scheduled_messages(
    statuses: list[str] | None = Query(default=None),
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return ScheduledMessageService(db).list_scheduled_messages(tenant_id, statuses=statuses)


@router.post("", response_model=ScheduledMessageOut, status_code=201)
def create_scheduled_message(
    body: ScheduledMessageCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    try:
        return ScheduledMessageService(db).create_scheduled_message(tenant_id, user.id, body)
    except AppError as e:
        raise _handle(e) from e


@router.get("/{scheduled_message_id}", response_model=ScheduledMessageOut)
def get_scheduled_message(
    scheduled_message_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return ScheduledMessageService(db).get_scheduled_message_out(tenant_id, scheduled_message_id)
    except AppError as e:
        raise _handle(e) from e


@router.put("/{scheduled_message_id}", response_model=ScheduledMessageOut)
def update_scheduled_message(
    scheduled_message_id: UUID,
    body: ScheduledMessageUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return ScheduledMessageService(db).update_scheduled_message(tenant_id, scheduled_message_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.post("/{scheduled_message_id}/reschedule", response_model=ScheduledMessageOut)
def reschedule_scheduled_message(
    scheduled_message_id: UUID,
    body: ScheduledMessageSchedule,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return ScheduledMessageService(db).reschedule(tenant_id, scheduled_message_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.post("/{scheduled_message_id}/cancel", response_model=ScheduledMessageOut)
def cancel_scheduled_message(
    scheduled_message_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return ScheduledMessageService(db).cancel_scheduled_message(tenant_id, scheduled_message_id)
    except AppError as e:
        raise _handle(e) from e


@router.delete("/{scheduled_message_id}", status_code=204)
def delete_scheduled_message(
    scheduled_message_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        ScheduledMessageService(db).delete_scheduled_message(tenant_id, scheduled_message_id)
    except AppError as e:
        raise _handle(e) from e
