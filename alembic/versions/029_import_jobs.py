"""Tabla import_jobs para importaciones masivas (GCS + Celery).

Revision ID: 029_import_jobs
Revises: 028_import_unique_indexes
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "029_import_jobs"
down_revision = "028_import_unique_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "import_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("module", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=500), nullable=False),
        sa.Column("gcs_path", sa.String(length=1000), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("inserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("registered", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_import_jobs_tenant_id", "import_jobs", ["tenant_id"])
    op.create_index("ix_import_jobs_module", "import_jobs", ["module"])
    op.create_index("ix_import_jobs_state", "import_jobs", ["state"])
    op.create_index("ix_import_jobs_celery_task_id", "import_jobs", ["celery_task_id"])
    op.create_index("ix_import_jobs_created_by_id", "import_jobs", ["created_by_id"])


def downgrade() -> None:
    op.drop_index("ix_import_jobs_created_by_id", table_name="import_jobs")
    op.drop_index("ix_import_jobs_celery_task_id", table_name="import_jobs")
    op.drop_index("ix_import_jobs_state", table_name="import_jobs")
    op.drop_index("ix_import_jobs_module", table_name="import_jobs")
    op.drop_index("ix_import_jobs_tenant_id", table_name="import_jobs")
    op.drop_table("import_jobs")
