from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import and_, exists, func, select
from sqlalchemy.orm import Session

from app.modules.campaigns.models import Campaign, CampaignSegment
from app.modules.reports.schemas import (
    CampaignReportFilters,
    CampaignReportRow,
    CampaignsByStatusItem,
    DashboardKpis,
    DashboardResponse,
    MessagesTimeseriesItem,
)
from app.modules.segments.models import Segment


class ReportsService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def _date_range(self, date_from: date | None, date_to: date | None) -> tuple[date, date]:
        today = datetime.now(timezone.utc).date()
        d_to = date_to or today
        d_from = date_from or (d_to - timedelta(days=29))
        return d_from, d_to

    def dashboard(
        self,
        tenant_id: UUID,
        *,
        date_from: date | None = None,
        date_to: date | None = None,
        campaign_id: UUID | None = None,
    ) -> DashboardResponse:
        d_from, d_to = self._date_range(date_from, date_to)

        base = select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.is_deleted.is_(False))
        if campaign_id:
            base = base.where(Campaign.id == campaign_id)

        kpi_stmt = base.with_only_columns(
            func.coalesce(func.sum(Campaign.sent_count), 0).label("sent"),
            func.coalesce(func.sum(Campaign.delivered_count), 0).label("delivered"),
            func.coalesce(func.sum(Campaign.failed_count), 0).label("failed"),
            func.coalesce(func.sum(Campaign.read_count), 0).label("read"),
            func.coalesce(func.sum(Campaign.response_count), 0).label("responses"),
            func.coalesce(func.sum(Campaign.estimated_cost), 0).label("cost"),
        )
        row = self.db.execute(kpi_stmt).one()
        sent = int(row.sent or 0)
        delivered = int(row.delivered or 0)
        read = int(row.read or 0)
        kpis = DashboardKpis(
            messages_sent=sent,
            messages_delivered=delivered,
            messages_failed=int(row.failed or 0),
            messages_read=read,
            responses_received=int(row.responses or 0),
            active_campaigns=int(
                self.db.scalar(
                    select(func.count(Campaign.id)).where(
                        Campaign.tenant_id == tenant_id,
                        Campaign.is_deleted.is_(False),
                        Campaign.status.in_(["en_curso", "programada"]),
                    )
                )
                or 0
            ),
            estimated_cost=float(row.cost or 0),
            read_rate=(float(read) / float(delivered)) * 100.0 if delivered else 0.0,
        )

        status_rows = self.db.execute(
            select(Campaign.status, func.count(Campaign.id))
            .where(Campaign.tenant_id == tenant_id, Campaign.is_deleted.is_(False))
            .group_by(Campaign.status)
        ).all()
        campaigns_by_status = [
            CampaignsByStatusItem(status=r[0], count=int(r[1])) for r in status_rows
        ]

        timeseries: list[MessagesTimeseriesItem] = []
        rows = self.db.execute(
            select(
                func.date(Campaign.sent_at).label("d"),
                func.coalesce(func.sum(Campaign.sent_count), 0).label("sent"),
                func.coalesce(func.sum(Campaign.delivered_count), 0).label("delivered"),
            )
            .where(
                Campaign.tenant_id == tenant_id,
                Campaign.is_deleted.is_(False),
                Campaign.sent_at.is_not(None),
                func.date(Campaign.sent_at) >= d_from,
                func.date(Campaign.sent_at) <= d_to,
            )
            .group_by("d")
            .order_by("d")
        ).all()
        for r in rows:
            timeseries.append(
                MessagesTimeseriesItem(label=str(r.d), sent=int(r.sent or 0), delivered=int(r.delivered or 0))
            )

        return DashboardResponse(
            kpis=kpis,
            campaigns_by_status=campaigns_by_status,
            messages_timeseries=timeseries,
        )

    def campaigns_report(
        self,
        tenant_id: UUID,
        filters: CampaignReportFilters,
    ) -> list[CampaignReportRow]:
        conditions = [Campaign.tenant_id == tenant_id, Campaign.is_deleted.is_(False)]
        if filters.date_from:
            conditions.append(func.coalesce(func.date(Campaign.sent_at), Campaign.scheduled_date) >= filters.date_from)
        if filters.date_to:
            conditions.append(func.coalesce(func.date(Campaign.sent_at), Campaign.scheduled_date) <= filters.date_to)
        if filters.campaign_id:
            conditions.append(Campaign.id == filters.campaign_id)
        if filters.segment_id:
            conditions.append(
                exists().where(
                    CampaignSegment.campaign_id == Campaign.id,
                    CampaignSegment.segment_id == filters.segment_id,
                )
            )
        if filters.status:
            conditions.append(Campaign.status == filters.status)
        if filters.created_by_user_id:
            conditions.append(Campaign.created_by_user_id == filters.created_by_user_id)

        rows = list(
            self.db.scalars(
                select(Campaign).where(and_(*conditions)).order_by(Campaign.created_at.desc())
            ).all()
        )
        segment_labels: dict[UUID, str] = {}
        if rows:
            campaign_ids = [c.id for c in rows]
            pairs = self.db.execute(
                select(CampaignSegment.campaign_id, Segment.name)
                .join(Segment, Segment.id == CampaignSegment.segment_id)
                .where(CampaignSegment.campaign_id.in_(campaign_ids))
                .order_by(CampaignSegment.campaign_id, Segment.name)
            ).all()
            names_by_campaign: dict[UUID, list[str]] = defaultdict(list)
            for cid, name in pairs:
                names_by_campaign[cid].append(name)
            segment_labels = {cid: ", ".join(names) for cid, names in names_by_campaign.items()}

        result: list[CampaignReportRow] = []
        for c in rows:
            seg_name = segment_labels.get(c.id)
            result.append(
                CampaignReportRow(
                    campaign_id=c.id,
                    campaign_name=c.name,
                    segment_name=seg_name,
                    sent_at=c.sent_at,
                    sent_count=c.sent_count,
                    delivered_count=c.delivered_count,
                    failed_count=c.failed_count,
                    read_count=c.read_count,
                    response_count=c.response_count,
                    estimated_cost=float(c.estimated_cost or 0),
                )
            )
        return result
