"""Dependencias FastAPI para autorización por módulo (perfiles / roles)."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_tenant_id
from app.db.session import get_db
from app.modules.iam.models import User
from app.modules.iam.service import ComponentService
from app.modules.tenants.features import is_feature_enabled

PermissionAction = Literal["view", "create", "edit", "delete", "export"]


def _has_action(user: User, db: Session, tenant_id: UUID, code: str, action: PermissionAction) -> bool:
    if user.is_superadmin:
        return True
    perms = ComponentService(db).resolve_permission(tenant_id, user.id, code)
    if not perms:
        return False
    return bool(getattr(perms, action))


def require_permission(code: str, action: PermissionAction = "view"):
    """Exige permiso sobre un módulo (`ui_components.code`)."""

    def dep(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
        tenant_id: UUID = Depends(get_tenant_id),
    ) -> User:
        if not is_feature_enabled(db, tenant_id, code):
            raise HTTPException(status_code=403, detail="Módulo no habilitado para este tenant")
        if not _has_action(user, db, tenant_id, code, action):
            raise HTTPException(status_code=403, detail="No tiene permiso para esta acción")
        return user

    return dep


def require_any_permission(*codes: str, action: PermissionAction = "view"):
    """Exige permiso en al menos uno de los módulos indicados."""

    def dep(
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
        tenant_id: UUID = Depends(get_tenant_id),
    ) -> User:
        if user.is_superadmin:
            for code in codes:
                if is_feature_enabled(db, tenant_id, code):
                    return user
            raise HTTPException(status_code=403, detail="Módulo no habilitado para este tenant")
        svc = ComponentService(db)
        for code in codes:
            if not is_feature_enabled(db, tenant_id, code):
                continue
            perms = svc.resolve_permission(tenant_id, user.id, code)
            if perms and getattr(perms, action):
                return user
        raise HTTPException(status_code=403, detail="No tiene permiso para esta acción")

    return dep


def require_profile_admin(user: User = Depends(get_current_user), db: Session = Depends(get_db), tenant_id: UUID = Depends(get_tenant_id)) -> User:
    """Administración de usuarios, perfiles o superadmin."""
    if user.is_superadmin:
        return user
    if _has_action(user, db, tenant_id, "perfiles", "edit"):
        return user
    if _has_action(user, db, tenant_id, "usuarios", "edit"):
        return user
    raise HTTPException(status_code=403, detail="No tiene permiso de administración")
