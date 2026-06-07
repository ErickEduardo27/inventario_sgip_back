from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.constants import INVENTORY_UI_COMPONENT_CODES
from app.core.exceptions import AppError
from app.core.security import hash_password
from app.modules.iam.models import Role, RoleComponent, UIComponent, User
from app.modules.iam.repository import RoleRepository, UserRepository
from app.modules.iam.schemas import (
    ComponentPermissions,
    RoleCreate,
    RolePermissionRow,
    RolePermissionsWrite,
    RoleUpdate,
    UIComponentOut,
    UserComponentOut,
    UserCreate,
    UserUpdate,
)
from app.shared.utils.strings import normalize_email


SCOPE_ORDER: dict[str, int] = {
    "own": 0,
    "team": 1,
    "area": 2,
    "site": 3,
    "tenant": 4,
    "global": 5,
}


class UserService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = UserRepository(db)

    def list_users(self, tenant_id: UUID) -> list[User]:
        return self.repo.list_by_tenant(tenant_id)

    def get_user(self, tenant_id: UUID, user_id: UUID) -> User:
        u = self.repo.get(tenant_id, user_id)
        if not u:
            raise AppError("Usuario no encontrado", 404)
        return u

    def _load_roles(self, tenant_id: UUID, role_ids: list[UUID]) -> list[Role]:
        if not role_ids:
            return []
        unique_ids = list({rid for rid in role_ids})
        rows = list(
            self.db.scalars(
                select(Role).where(
                    Role.is_deleted.is_(False),
                    Role.id.in_(unique_ids),
                    (Role.tenant_id == tenant_id) | (Role.tenant_id.is_(None)),
                )
            ).all()
        )
        if len(rows) != len(unique_ids):
            raise AppError("Uno o más roles no existen en este tenant", 400)
        return rows

    def create_user(self, tenant_id: UUID, body: UserCreate) -> User:
        roles = self._load_roles(tenant_id, body.role_ids)
        u = User(
            tenant_id=tenant_id,
            full_name=body.full_name.strip(),
            email=normalize_email(str(body.email)),
            password_hash=hash_password(body.password),
            status=body.status,
            is_superadmin=body.is_superadmin,
            num_ini=body.num_ini,
            num_fin=body.num_fin,
            num_act=body.num_act,
            eti_ini=body.eti_ini,
            eti_fin=body.eti_fin,
            eti_act=body.eti_act,
        )
        u.roles = roles
        self.repo.add(u)
        try:
            self.db.commit()
            self.db.refresh(u)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_users_tenant_email" in str(e.orig) or "unique" in str(e.orig).lower():
                raise AppError("El email ya está registrado en este tenant", 409) from e
            raise AppError("No se pudo crear el usuario", 400) from e
        return u

    def update_user(self, tenant_id: UUID, user_id: UUID, body: UserUpdate) -> User:
        u = self.get_user(tenant_id, user_id)
        data = body.model_dump(exclude_unset=True)
        new_roles: list[Role] | None = None
        if "role_ids" in data:
            ids = data.pop("role_ids") or []
            new_roles = self._load_roles(tenant_id, ids)
        if "email" in data and data["email"]:
            data["email"] = normalize_email(str(data["email"]))
        if "password" in data and data["password"]:
            data["password_hash"] = hash_password(data["password"])
            del data["password"]
        for k, v in data.items():
            setattr(u, k, v)
        if new_roles is not None:
            u.roles = new_roles
        try:
            self.db.commit()
            self.db.refresh(u)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_users_tenant_email" in str(e.orig) or "unique" in str(e.orig).lower():
                raise AppError("El email ya está registrado en este tenant", 409) from e
            raise AppError("No se pudo actualizar el usuario", 400) from e
        return u

    def delete_user(self, tenant_id: UUID, user_id: UUID) -> None:
        u = self.get_user(tenant_id, user_id)
        u.is_deleted = True
        self.db.commit()


class RoleService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = RoleRepository(db)

    def list_roles(self, tenant_id: UUID) -> list[Role]:
        return self.repo.list_by_tenant(tenant_id)

    def get_role(self, tenant_id: UUID, role_id: UUID) -> Role:
        r = self.repo.get(tenant_id, role_id)
        if not r:
            raise AppError("Rol no encontrado", 404)
        return r

    def create_role(self, tenant_id: UUID, body: RoleCreate) -> Role:
        r = Role(
            tenant_id=tenant_id,
            name=body.name.strip(),
            code=body.code.strip().lower(),
            description=(body.description or "").strip(),
            is_system=body.is_system,
        )
        self.repo.add(r)
        try:
            self.db.commit()
            self.db.refresh(r)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_roles_tenant_code" in str(e.orig) or "unique" in str(e.orig).lower():
                raise AppError("Ya existe un rol con ese código en este tenant", 409) from e
            raise AppError("No se pudo crear el rol", 400) from e
        return r

    def update_role(self, tenant_id: UUID, role_id: UUID, body: RoleUpdate) -> Role:
        r = self.get_role(tenant_id, role_id)
        if r.tenant_id is None:
            raise AppError("No se puede modificar un rol global del sistema", 400)
        data = body.model_dump(exclude_unset=True)
        if "code" in data and data["code"]:
            data["code"] = data["code"].strip().lower()
        if "name" in data and data["name"]:
            data["name"] = data["name"].strip()
        if "description" in data and data["description"] is not None:
            data["description"] = data["description"].strip()
        for k, v in data.items():
            setattr(r, k, v)
        try:
            self.db.commit()
            self.db.refresh(r)
        except IntegrityError as e:
            self.db.rollback()
            if "uq_roles_tenant_code" in str(e.orig) or "unique" in str(e.orig).lower():
                raise AppError("Ya existe un rol con ese código en este tenant", 409) from e
            raise AppError("No se pudo actualizar el rol", 400) from e
        return r

    def delete_role(self, tenant_id: UUID, role_id: UUID) -> None:
        r = self.get_role(tenant_id, role_id)
        if r.is_system or r.tenant_id is None:
            raise AppError("No se puede eliminar un perfil del sistema", 400)
        r.is_deleted = True
        self.db.commit()

    def list_inventory_components(self) -> list[UIComponentOut]:
        rows = list(
            self.db.scalars(
                select(UIComponent)
                .where(
                    UIComponent.status == "active",
                    UIComponent.code.in_(INVENTORY_UI_COMPONENT_CODES),
                )
                .order_by(UIComponent.order_index)
            ).all()
        )
        return [UIComponentOut.model_validate(r) for r in rows]

    def get_role_permissions(self, tenant_id: UUID, role_id: UUID) -> list[RolePermissionRow]:
        role = self.get_role(tenant_id, role_id)
        components = list(
            self.db.scalars(
                select(UIComponent)
                .where(
                    UIComponent.status == "active",
                    UIComponent.code.in_(INVENTORY_UI_COMPONENT_CODES),
                )
                .order_by(UIComponent.order_index)
            ).all()
        )
        existing = {
            rc.component_id: rc
            for rc in self.db.scalars(
                select(RoleComponent).where(RoleComponent.role_id == role.id)
            ).all()
        }
        out: list[RolePermissionRow] = []
        for comp in components:
            rc = existing.get(comp.id)
            out.append(
                RolePermissionRow(
                    component_code=comp.code,
                    component_name=comp.name,
                    group_name=comp.group_name,
                    can_view=bool(rc.can_view) if rc else False,
                    can_create=bool(rc.can_create) if rc else False,
                    can_edit=bool(rc.can_edit) if rc else False,
                    can_delete=bool(rc.can_delete) if rc else False,
                    can_export=bool(rc.can_export) if rc else False,
                    scope=rc.scope if rc else "tenant",
                )
            )
        return out

    def set_role_permissions(
        self, tenant_id: UUID, role_id: UUID, body: RolePermissionsWrite
    ) -> list[RolePermissionRow]:
        role = self.get_role(tenant_id, role_id)
        components = list(
            self.db.scalars(
                select(UIComponent).where(
                    UIComponent.status == "active",
                    UIComponent.code.in_(INVENTORY_UI_COMPONENT_CODES),
                )
            ).all()
        )
        comp_by_code = {c.code: c for c in components}
        allowed_codes = set(comp_by_code.keys())
        for row in body.permissions:
            if row.component_code not in allowed_codes:
                raise AppError(f"Módulo no válido: {row.component_code}", 400)

        self.db.execute(delete(RoleComponent).where(RoleComponent.role_id == role.id))
        for row in body.permissions:
            if not row.can_view:
                continue
            comp = comp_by_code[row.component_code]
            self.db.add(
                RoleComponent(
                    role_id=role.id,
                    component_id=comp.id,
                    can_view=row.can_view,
                    can_create=row.can_create,
                    can_edit=row.can_edit,
                    can_delete=row.can_delete,
                    can_export=row.can_export,
                    scope=row.scope or "tenant",
                )
            )
        self.db.commit()
        return self.get_role_permissions(tenant_id, role_id)


class ComponentService:
    """Resuelve los componentes visibles (y sus permisos) para un usuario."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_for_user(self, tenant_id: UUID, user_id: UUID) -> list[UserComponentOut]:
        user = UserRepository(self.db).get(tenant_id, user_id)
        if not user:
            raise AppError("Usuario no encontrado", 404)

        all_components = list(
            self.db.scalars(
                select(UIComponent)
                .where(
                    UIComponent.status == "active",
                    UIComponent.code.in_(INVENTORY_UI_COMPONENT_CODES),
                )
                .order_by(UIComponent.order_index)
            ).all()
        )

        if user.is_superadmin:
            return [
                UserComponentOut(
                    code=c.code,
                    name=c.name,
                    group_name=c.group_name,
                    route=c.route,
                    icon=c.icon,
                    is_portal=c.is_portal,
                    order_index=c.order_index,
                    permissions=ComponentPermissions(
                        view=True, create=True, edit=True, delete=True, export=True, scope="tenant"
                    ),
                )
                for c in all_components
            ]

        role_ids = [r.id for r in user.roles]
        if not role_ids:
            return []

        rows = list(
            self.db.execute(
                select(UIComponent, RoleComponent)
                .join(RoleComponent, RoleComponent.component_id == UIComponent.id)
                .where(
                    RoleComponent.role_id.in_(role_ids),
                    UIComponent.status == "active",
                    UIComponent.code.in_(INVENTORY_UI_COMPONENT_CODES),
                )
                .order_by(UIComponent.order_index)
            ).all()
        )

        merged: dict[UUID, tuple[UIComponent, dict]] = {}
        for comp, rc in rows:
            if not rc.can_view:
                continue
            current = merged.get(comp.id)
            if current is None:
                merged[comp.id] = (
                    comp,
                    {
                        "view": bool(rc.can_view),
                        "create": bool(rc.can_create),
                        "edit": bool(rc.can_edit),
                        "delete": bool(rc.can_delete),
                        "export": bool(rc.can_export),
                        "scope": rc.scope,
                    },
                )
                continue
            _, perms = current
            perms["view"] = perms["view"] or bool(rc.can_view)
            perms["create"] = perms["create"] or bool(rc.can_create)
            perms["edit"] = perms["edit"] or bool(rc.can_edit)
            perms["delete"] = perms["delete"] or bool(rc.can_delete)
            perms["export"] = perms["export"] or bool(rc.can_export)
            if SCOPE_ORDER.get(rc.scope, 0) > SCOPE_ORDER.get(perms["scope"], 0):
                perms["scope"] = rc.scope

        ordered = sorted(merged.values(), key=lambda item: item[0].order_index)
        return [
            UserComponentOut(
                code=c.code,
                name=c.name,
                group_name=c.group_name,
                route=c.route,
                icon=c.icon,
                is_portal=c.is_portal,
                order_index=c.order_index,
                permissions=ComponentPermissions(**p),
            )
            for c, p in ordered
        ]

    def resolve_permission(
        self, tenant_id: UUID, user_id: UUID, component_code: str
    ) -> ComponentPermissions | None:
        if component_code not in INVENTORY_UI_COMPONENT_CODES:
            return None
        user = UserRepository(self.db).get(tenant_id, user_id)
        if not user:
            return None
        if user.is_superadmin:
            return ComponentPermissions(
                view=True, create=True, edit=True, delete=True, export=True, scope="tenant"
            )
        role_ids = [r.id for r in user.roles]
        if not role_ids:
            return None
        rows = list(
            self.db.execute(
                select(RoleComponent, UIComponent)
                .join(UIComponent, UIComponent.id == RoleComponent.component_id)
                .where(
                    RoleComponent.role_id.in_(role_ids),
                    UIComponent.code == component_code,
                    UIComponent.status == "active",
                )
            ).all()
        )
        if not rows:
            return None
        merged = {
            "view": False,
            "create": False,
            "edit": False,
            "delete": False,
            "export": False,
            "scope": "tenant",
        }
        for rc, _ui in rows:
            if rc.can_view:
                merged["view"] = True
            if rc.can_create:
                merged["create"] = True
            if rc.can_edit:
                merged["edit"] = True
            if rc.can_delete:
                merged["delete"] = True
            if rc.can_export:
                merged["export"] = True
            if SCOPE_ORDER.get(rc.scope, 0) > SCOPE_ORDER.get(merged["scope"], 0):
                merged["scope"] = rc.scope
        if not merged["view"]:
            return None
        return ComponentPermissions(**merged)
