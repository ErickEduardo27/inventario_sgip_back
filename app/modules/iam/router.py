from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_id
from app.core.exceptions import AppError
from app.db.session import get_db
from app.modules.iam.dependencies import require_profile_admin
from app.modules.iam.models import User
from app.modules.iam.schemas import (
    RoleCreate,
    RoleOut,
    RolePermissionRow,
    RolePermissionsWrite,
    RoleUpdate,
    UIComponentOut,
    PagedUserRows,
    UserComponentOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.modules.iam.service import ComponentService, RoleService, UserService

router = APIRouter()


def _handle(err: AppError) -> HTTPException:
    return HTTPException(status_code=err.status_code, detail=err.message)


@router.get("/users", response_model=list[UserOut])
def list_users(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _user: User = Depends(require_profile_admin),
):
    return UserService(db).list_users(tenant_id)


@router.get("/users/records", response_model=PagedUserRows)
def list_users_paged(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _user: User = Depends(require_profile_admin),
    page: int = Query(1, ge=1),
    per_page: int = Query(15, ge=1, le=200),
    search: str | None = Query(None),
):
    return UserService(db).list_users_paged(tenant_id, page=page, per_page=per_page, search=search)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _user: User = Depends(require_profile_admin),
):
    try:
        return UserService(db).get_user(tenant_id, user_id)
    except AppError as e:
        raise _handle(e) from e


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(
    body: UserCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _user: User = Depends(require_profile_admin),
):
    try:
        return UserService(db).create_user(tenant_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.put("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: UUID,
    body: UserUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _user: User = Depends(require_profile_admin),
):
    try:
        return UserService(db).update_user(tenant_id, user_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _user: User = Depends(require_profile_admin),
):
    try:
        UserService(db).delete_user(tenant_id, user_id)
    except AppError as e:
        raise _handle(e) from e


@router.get("/roles", response_model=list[RoleOut])
def list_roles(
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _user: User = Depends(get_current_user),
):
    return RoleService(db).list_roles(tenant_id)


@router.get("/roles/{role_id}", response_model=RoleOut)
def get_role(
    role_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _user: User = Depends(get_current_user),
):
    try:
        return RoleService(db).get_role(tenant_id, role_id)
    except AppError as e:
        raise _handle(e) from e


@router.post("/roles", response_model=RoleOut, status_code=201)
def create_role(
    body: RoleCreate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _user: User = Depends(require_profile_admin),
):
    try:
        payload = body.model_copy(update={"is_system": False})
        return RoleService(db).create_role(tenant_id, payload)
    except AppError as e:
        raise _handle(e) from e


@router.put("/roles/{role_id}", response_model=RoleOut)
def update_role(
    role_id: UUID,
    body: RoleUpdate,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _user: User = Depends(require_profile_admin),
):
    try:
        return RoleService(db).update_role(tenant_id, role_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.delete("/roles/{role_id}", status_code=204)
def delete_role(
    role_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _user: User = Depends(require_profile_admin),
):
    try:
        RoleService(db).delete_role(tenant_id, role_id)
    except AppError as e:
        raise _handle(e) from e


@router.get("/components", response_model=list[UIComponentOut])
def list_components(
    db: Session = Depends(get_db),
    _user: User = Depends(require_profile_admin),
):
    return RoleService(db).list_inventory_components()


@router.get("/roles/{role_id}/permissions", response_model=list[RolePermissionRow])
def get_role_permissions(
    role_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _user: User = Depends(require_profile_admin),
):
    try:
        return RoleService(db).get_role_permissions(tenant_id, role_id)
    except AppError as e:
        raise _handle(e) from e


@router.put("/roles/{role_id}/permissions", response_model=list[RolePermissionRow])
def set_role_permissions(
    role_id: UUID,
    body: RolePermissionsWrite,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    _user: User = Depends(require_profile_admin),
):
    try:
        return RoleService(db).set_role_permissions(tenant_id, role_id, body)
    except AppError as e:
        raise _handle(e) from e


@router.get("/users/{user_id}/components", response_model=list[UserComponentOut])
def list_user_components(
    user_id: UUID,
    db: Session = Depends(get_db),
    tenant_id: UUID = Depends(get_tenant_id),
    user: User = Depends(get_current_user),
):
    """Componentes visibles (sidebar) y permisos resueltos para el usuario dado."""
    if user.id != user_id and not user.is_superadmin:
        require_profile_admin(user=user, db=db, tenant_id=tenant_id)
    try:
        return ComponentService(db).list_for_user(tenant_id, user_id)
    except AppError as e:
        raise _handle(e) from e
