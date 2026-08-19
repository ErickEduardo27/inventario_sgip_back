from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_id
from app.core.exceptions import AppError
from app.db.session import get_db
from app.modules.auth.schemas import LoginRequest, LoginResponse, ProfileUpdate, SessionOut
from app.modules.auth.service import AuthService
from app.modules.iam.models import User
from app.modules.iam.schemas import UserOut
from app.modules.iam.service import ComponentService

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
def login(
    body: LoginRequest,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
):
    try:
        return AuthService(db).login(tenant_id, body)
    except AppError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e


@router.get("/me", response_model=SessionOut)
def me(
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        components = ComponentService(db).list_for_user(current.tenant_id, current.id)
    except AppError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return SessionOut(user=current, components=components)


@router.patch("/me", response_model=UserOut)
def update_me(
    body: ProfileUpdate,
    current: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        user = AuthService(db).update_own_profile(current, body)
    except AppError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    return UserOut.model_validate(user)
