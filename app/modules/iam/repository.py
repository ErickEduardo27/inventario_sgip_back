from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.modules.iam.models import Role, User


def _user_search_pattern(search: str | None) -> str | None:
    q = (search or "").strip()
    return f"%{q}%" if q else None


class UserRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_tenant(self, tenant_id: UUID) -> list[User]:
        return list(
            self.db.scalars(
                select(User).where(User.tenant_id == tenant_id, User.is_deleted.is_(False)).order_by(User.full_name)
            ).all()
        )

    def list_by_tenant_paged(
        self,
        tenant_id: UUID,
        *,
        page: int,
        per_page: int,
        search: str | None = None,
    ) -> tuple[list[User], int]:
        filters = [User.tenant_id == tenant_id, User.is_deleted.is_(False)]
        pattern = _user_search_pattern(search)
        if pattern:
            filters.append(
                or_(
                    User.full_name.ilike(pattern),
                    User.email.ilike(pattern),
                    User.status.ilike(pattern),
                )
            )
        total = int(self.db.scalar(select(func.count(User.id)).where(*filters)) or 0)
        rows = list(
            self.db.scalars(
                select(User)
                .where(*filters)
                .order_by(User.full_name)
                .offset(max(0, (page - 1) * per_page))
                .limit(per_page)
            ).all()
        )
        return rows, total

    def get(self, tenant_id: UUID, user_id: UUID) -> User | None:
        return self.db.scalar(
            select(User).where(
                User.id == user_id,
                User.tenant_id == tenant_id,
                User.is_deleted.is_(False),
            )
        )

    def add(self, entity: User) -> User:
        self.db.add(entity)
        return entity

    def delete(self, entity: User) -> None:
        self.db.delete(entity)


class RoleRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list_by_tenant(self, tenant_id: UUID) -> list[Role]:
        """Roles visibles para el tenant: los suyos + los globales (tenant_id IS NULL)."""
        return list(
            self.db.scalars(
                select(Role)
                .where(
                    Role.is_deleted.is_(False),
                    or_(Role.tenant_id == tenant_id, Role.tenant_id.is_(None)),
                )
                .order_by(Role.tenant_id.is_(None).desc(), Role.name)
            ).all()
        )

    def get(self, tenant_id: UUID, role_id: UUID) -> Role | None:
        """Devuelve rol del tenant o rol global."""
        return self.db.scalar(
            select(Role).where(
                Role.id == role_id,
                Role.is_deleted.is_(False),
                or_(Role.tenant_id == tenant_id, Role.tenant_id.is_(None)),
            )
        )

    def add(self, entity: Role) -> Role:
        self.db.add(entity)
        return entity
