from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_id
from app.core.exceptions import AppError
from app.db.session import get_db
from app.modules.iam.models import User
from app.modules.segments.schemas import (
    SegmentCreate,
    SegmentCriteria,
    SegmentOut,
    SegmentPreview,
    SegmentUpdate,
)
from app.modules.segments.service import SegmentService

router = APIRouter()


def _handle(err: AppError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.message)


@router.get("", response_model=list[SegmentOut])
def list_segments(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return SegmentService(db).list_segments(tenant_id)


@router.post("/preview", response_model=SegmentPreview)
def preview(
    criteria: SegmentCriteria,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return SegmentPreview(contact_count=SegmentService(db).preview_count(tenant_id, criteria))


@router.get("/{segment_id}", response_model=SegmentOut)
def get_segment(
    segment_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return SegmentService(db).get_segment_out(tenant_id, segment_id)
    except AppError as e:
        raise _handle(e) from e


@router.post("", response_model=SegmentOut, status_code=201)
def create_segment(
    body: SegmentCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return SegmentService(db).create_segment(tenant_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.put("/{segment_id}", response_model=SegmentOut)
def update_segment(
    segment_id: UUID,
    body: SegmentUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return SegmentService(db).update_segment(tenant_id, segment_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.delete("/{segment_id}", status_code=204)
def delete_segment(
    segment_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        SegmentService(db).delete_segment(tenant_id, segment_id)
    except AppError as e:
        raise _handle(e) from e
