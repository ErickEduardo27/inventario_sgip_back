from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.tenants.models import Tenant
from app.modules.tenants.repository import TenantRepository


class TenantService:
    def __init__(self, db: Session) -> None:
        self.repo = TenantRepository(db)

    def get_public_by_slug(self, slug: str) -> Tenant:
        t = self.repo.get_by_slug(slug)
        if not t:
            raise AppError("Tenant no encontrado", 404)
        if t.status != "active":
            raise AppError("Tenant no disponible", 403)
        return t
