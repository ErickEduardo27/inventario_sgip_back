from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.tenant_logo_storage import delete_tenant_logo_object, upload_tenant_logo
from app.modules.settings.models import WorkspaceSettings
from app.modules.settings.schemas import SettingsUpdate
from app.modules.tenants.component_slots import merge_custom_components
from app.modules.tenants.features import merge_features
from app.modules.tenants.theme import merge_theme


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
        if "portal_branding" in data:
            data["portal_branding"] = merge_theme(s.portal_branding, data.get("portal_branding"))
        if "feature_flags" in data:
            data["feature_flags"] = merge_features(
                {**(s.feature_flags or {}), **(data.get("feature_flags") or {})}
            )
        if "custom_components" in data:
            data["custom_components"] = merge_custom_components(
                {**(s.custom_components or {}), **(data.get("custom_components") or {})}
            )
        for k, v in data.items():
            setattr(s, k, v)
        self.db.commit()
        self.db.refresh(s)
        return s

    def upload_logo(self, tenant_id: UUID, content: bytes, content_type: str) -> WorkspaceSettings:
        s = self._get_or_create(tenant_id)
        delete_tenant_logo_object(s.logo_url, tenant_id)
        s.logo_url = upload_tenant_logo(
            tenant_id=tenant_id, content=content, content_type=content_type, kind="portal"
        )
        self.db.commit()
        self.db.refresh(s)
        return s

    def clear_logo(self, tenant_id: UUID) -> WorkspaceSettings:
        s = self._get_or_create(tenant_id)
        delete_tenant_logo_object(s.logo_url, tenant_id)
        s.logo_url = None
        self.db.commit()
        self.db.refresh(s)
        return s

    def upload_pdf_logo(self, tenant_id: UUID, content: bytes, content_type: str) -> WorkspaceSettings:
        s = self._get_or_create(tenant_id)
        delete_tenant_logo_object(s.pdf_logo_url, tenant_id)
        s.pdf_logo_url = upload_tenant_logo(
            tenant_id=tenant_id, content=content, content_type=content_type, kind="pdf"
        )
        self.db.commit()
        self.db.refresh(s)
        return s

    def clear_pdf_logo(self, tenant_id: UUID) -> WorkspaceSettings:
        s = self._get_or_create(tenant_id)
        delete_tenant_logo_object(s.pdf_logo_url, tenant_id)
        s.pdf_logo_url = None
        self.db.commit()
        self.db.refresh(s)
        return s
