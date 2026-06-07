from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_id
from app.core.exceptions import AppError
from app.db.session import get_db
from app.modules.iam.models import User
from app.modules.surveys.schemas import SurveyCreate, SurveyOut, SurveyUpdate
from app.modules.surveys.service import SurveyService

router = APIRouter()


def _handle(err: AppError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.message)


@router.get("", response_model=list[SurveyOut])
def list_surveys(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    return SurveyService(db).list_surveys(tenant_id)


@router.get("/{survey_id}", response_model=SurveyOut)
def get_survey(
    survey_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return SurveyService(db).get_survey_out(tenant_id, survey_id)
    except AppError as e:
        raise _handle(e) from e


@router.post("", response_model=SurveyOut, status_code=201)
def create_survey(
    body: SurveyCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return SurveyService(db).create_survey(tenant_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.put("/{survey_id}", response_model=SurveyOut)
def update_survey(
    survey_id: UUID,
    body: SurveyUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        return SurveyService(db).update_survey(tenant_id, survey_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.delete("/{survey_id}", status_code=204)
def delete_survey(
    survey_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _: User = Depends(get_current_user),
):
    try:
        SurveyService(db).delete_survey(tenant_id, survey_id)
    except AppError as e:
        raise _handle(e) from e
