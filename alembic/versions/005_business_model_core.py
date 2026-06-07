"""Modelo de negocio: mensajes programados, envíos, segmentos manuales, respuestas encuesta.

Revision ID: 005_business_model_core
Revises: 004_contact_catalog
Create Date: 2026-05-03
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

revision = "005_business_model_core"
down_revision = "004_contact_catalog"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "campaign_segments",
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("campaign_id", "segment_id"),
    )
    op.create_index(op.f("ix_campaign_segments_segment_id"), "campaign_segments", ["segment_id"])

    op.create_table(
        "campaign_templates",
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["template_id"], ["message_templates.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("campaign_id", "template_id"),
    )

    op.add_column("campaigns", sa.Column("start_date", sa.Date(), nullable=True))
    op.add_column("campaigns", sa.Column("end_date", sa.Date(), nullable=True))
    op.add_column("campaigns", sa.Column("observation", sa.Text(), nullable=True))

    op.create_table(
        "scheduled_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contenido_final", sa.Text(), nullable=True),
        sa.Column("scheduled_date", sa.Date(), nullable=True),
        sa.Column("scheduled_time", sa.Time(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="borrador"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["template_id"], ["message_templates.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_scheduled_messages_tenant_id"), "scheduled_messages", ["tenant_id"])
    op.create_index(op.f("ix_scheduled_messages_campaign_id"), "scheduled_messages", ["campaign_id"])
    op.create_index(op.f("ix_scheduled_messages_status"), "scheduled_messages", ["status"])
    op.create_index(op.f("ix_scheduled_messages_scheduled_date"), "scheduled_messages", ["scheduled_date"])

    op.create_table(
        "scheduled_message_contacts",
        sa.Column("scheduled_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scheduled_message_id"], ["scheduled_messages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("scheduled_message_id", "contact_id"),
    )

    op.create_table(
        "scheduled_message_segments",
        sa.Column("scheduled_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["scheduled_message_id"], ["scheduled_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("scheduled_message_id", "segment_id"),
    )

    op.create_table(
        "segment_manual_contacts",
        sa.Column("segment_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["segment_id"], ["segments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("segment_id", "contact_id"),
    )

    op.create_table(
        "delivery_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scheduled_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("whatsapp_number", sa.String(length=50), nullable=False),
        sa.Column("message_sent", sa.Text(), nullable=True),
        sa.Column("delivery_status", sa.String(length=40), nullable=False, server_default="pendiente"),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(precision=12, scale=2), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["scheduled_message_id"], ["scheduled_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_delivery_logs_tenant_id"), "delivery_logs", ["tenant_id"])
    op.create_index(op.f("ix_delivery_logs_scheduled_message_id"), "delivery_logs", ["scheduled_message_id"])
    op.create_index(op.f("ix_delivery_logs_campaign_id"), "delivery_logs", ["campaign_id"])
    op.create_index(op.f("ix_delivery_logs_contact_id"), "delivery_logs", ["contact_id"])

    op.create_table(
        "survey_responses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("survey_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("campaign_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("response", sa.Text(), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["campaign_id"], ["campaigns.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["survey_id"], ["surveys.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_survey_responses_tenant_id"), "survey_responses", ["tenant_id"])
    op.create_index(op.f("ix_survey_responses_survey_id"), "survey_responses", ["survey_id"])

    bind = op.get_bind()

    bind.execute(
        text(
            """
            INSERT INTO campaign_segments (campaign_id, segment_id)
            SELECT c.id, c.segment_id FROM campaigns c
            WHERE c.segment_id IS NOT NULL AND c.is_deleted = false
              AND NOT EXISTS (
                SELECT 1 FROM campaign_segments cs
                WHERE cs.campaign_id = c.id AND cs.segment_id = c.segment_id
              )
            """
        )
    )
    bind.execute(
        text(
            """
            INSERT INTO campaign_templates (campaign_id, template_id)
            SELECT c.id, c.template_id FROM campaigns c
            WHERE c.template_id IS NOT NULL AND c.is_deleted = false
              AND NOT EXISTS (
                SELECT 1 FROM campaign_templates ct
                WHERE ct.campaign_id = c.id AND ct.template_id = c.template_id
              )
            """
        )
    )

    rows = bind.execute(
        text(
            """
            SELECT id, tenant_id, segment_id, template_id, custom_message, scheduled_date, scheduled_time,
                   status, created_by_user_id, created_at, updated_at
            FROM campaigns WHERE is_deleted = false
            """
        )
    ).fetchall()

    for row in rows:
        (
            cid,
            tid,
            seg_id,
            tpl_id,
            custom_msg,
            s_date,
            s_time,
            st,
            creator,
            cat,
            uat,
        ) = row
        needs_sm = (
            seg_id is not None
            or tpl_id is not None
            or (custom_msg and str(custom_msg).strip())
            or s_date is not None
            or s_time is not None
            or st == "programada"
        )
        if not needs_sm:
            continue
        sm_id = uuid.uuid4()
        sm_status = "programado" if (s_date is not None or st == "programada") else "borrador"
        bind.execute(
            text(
                """
                INSERT INTO scheduled_messages (
                    id, created_at, updated_at, is_deleted, tenant_id, campaign_id,
                    template_id, contenido_final, scheduled_date, scheduled_time,
                    status, created_by_user_id
                )
                VALUES (
                    :id, :cat, :uat, false, :tid, :cid,
                    :tpl, :content, :sdate, :stime,
                    :smst, :creator
                )
                """
            ),
            {
                "id": sm_id,
                "cat": cat,
                "uat": uat,
                "tid": tid,
                "cid": cid,
                "tpl": tpl_id,
                "content": custom_msg,
                "sdate": s_date,
                "stime": s_time,
                "smst": sm_status,
                "creator": creator,
            },
        )
        if seg_id:
            bind.execute(
                text(
                    """
                    INSERT INTO scheduled_message_segments (scheduled_message_id, segment_id)
                    VALUES (:sm, :seg)
                    """
                ),
                {"sm": sm_id, "seg": seg_id},
            )

    bind.execute(text("ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_segment_id_fkey"))
    bind.execute(text("ALTER TABLE campaigns DROP CONSTRAINT IF EXISTS campaigns_template_id_fkey"))
    op.drop_index(op.f("ix_campaigns_segment_id"), table_name="campaigns")
    op.drop_index(op.f("ix_campaigns_template_id"), table_name="campaigns")
    op.drop_index(op.f("ix_campaigns_scheduled_date"), table_name="campaigns")

    op.drop_column("campaigns", "segment_id")
    op.drop_column("campaigns", "template_id")
    op.drop_column("campaigns", "custom_message")
    op.drop_column("campaigns", "scheduled_date")
    op.drop_column("campaigns", "scheduled_time")
    op.drop_column("campaigns", "attachment_filename")


def downgrade() -> None:
    pass
