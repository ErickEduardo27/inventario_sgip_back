from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.settings.models import WorkspaceSettings
from app.modules.settings.schemas import SettingsUpdate


class SettingsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _get_or_create(self, tenant_id: UUID) -> WorkspaceSettings:
        s = self.db.scalar(select(WorkspaceSettings).where(WorkspaceSettings.tenant_id == tenant_id))
        if s:
            return s
        s = WorkspaceSettings(tenant_id=tenant_id)
        self.db.add(s)
        self.db.commit()
        self.db.refresh(s)
        return s

    def get_settings(self, tenant_id: UUID) -> WorkspaceSettings:
        return self._get_or_create(tenant_id)

    def update_settings(self, tenant_id: UUID, body: SettingsUpdate) -> WorkspaceSettings:
        s = self._get_or_create(tenant_id)
        data = body.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(s, k, v)
        self.db.commit()
        self.db.refresh(s)
        return s
