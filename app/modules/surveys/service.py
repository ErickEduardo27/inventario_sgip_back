from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.modules.campaigns.models import Campaign
from app.modules.segments.models import Segment
from app.modules.surveys.models import Survey
from app.modules.surveys.schemas import SurveyCreate, SurveyOut, SurveyUpdate


class SurveyService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _to_out(self, s: Survey) -> SurveyOut:
        camp_name = None
        if s.campaign_id:
            camp_name = self.db.scalar(select(Campaign.name).where(Campaign.id == s.campaign_id))
        seg_name = None
        if s.segment_id:
            seg_name = self.db.scalar(select(Segment.name).where(Segment.id == s.segment_id))
        return SurveyOut(
            id=s.id,
            tenant_id=s.tenant_id,
            name=s.name,
            question=s.question,
            response_type=s.response_type,
            options=list(s.options or []),
            campaign_id=s.campaign_id,
            segment_id=s.segment_id,
            status=s.status,
            response_count=s.response_count,
            campaign_name=camp_name,
            segment_name=seg_name,
            created_at=s.created_at,
        )

    def list_surveys(self, tenant_id: UUID) -> list[SurveyOut]:
        rows = list(
            self.db.scalars(
                select(Survey)
                .where(Survey.tenant_id == tenant_id, Survey.is_deleted.is_(False))
                .order_by(Survey.created_at.desc())
            ).all()
        )
        return [self._to_out(s) for s in rows]

    def get_survey(self, tenant_id: UUID, survey_id: UUID) -> Survey:
        s = self.db.scalar(
            select(Survey).where(
                Survey.id == survey_id,
                Survey.tenant_id == tenant_id,
                Survey.is_deleted.is_(False),
            )
        )
        if not s:
            raise AppError("Encuesta no encontrada", 404)
        return s

    def get_survey_out(self, tenant_id: UUID, survey_id: UUID) -> SurveyOut:
        return self._to_out(self.get_survey(tenant_id, survey_id))

    def create_survey(self, tenant_id: UUID, body: SurveyCreate) -> SurveyOut:
        s = Survey(
            tenant_id=tenant_id,
            name=body.name.strip(),
            question=body.question,
            response_type=body.response_type,
            options=body.options or [],
            campaign_id=body.campaign_id,
            segment_id=body.segment_id,
            status=body.status,
        )
        self.db.add(s)
        self.db.commit()
        self.db.refresh(s)
        return self._to_out(s)

    def update_survey(self, tenant_id: UUID, survey_id: UUID, body: SurveyUpdate) -> SurveyOut:
        s = self.get_survey(tenant_id, survey_id)
        data = body.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(s, k, v)
        self.db.commit()
        self.db.refresh(s)
        return self._to_out(s)

    def delete_survey(self, tenant_id: UUID, survey_id: UUID) -> None:
        s = self.get_survey(tenant_id, survey_id)
        s.is_deleted = True
        self.db.commit()
