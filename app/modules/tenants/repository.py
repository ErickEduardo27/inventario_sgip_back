from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.tenants.models import Tenant


class TenantRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_slug(self, slug: str) -> Tenant | None:
        return self.db.scalar(select(Tenant).where(Tenant.slug == slug.strip().lower()))
