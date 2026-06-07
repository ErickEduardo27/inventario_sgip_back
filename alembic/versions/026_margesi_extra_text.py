"""``margesi.extra``: JSONB → TEXT (importación CSV con token ``NULL``)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "026_margesi_extra_text"
down_revision = "025_margesi_inv_con_10"
branch_labels = None
depends_on = None


def _extra_is_text(conn: sa.Connection) -> bool:
    row = conn.execute(
        sa.text(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'margesi'
              AND column_name = 'extra'
            """
        )
    ).first()
    return bool(row and str(row[0]).lower() in ("text", "character varying"))


def upgrade() -> None:
    conn = op.get_bind()
    if _extra_is_text(conn):
        return
    op.alter_column(
        "margesi",
        "extra",
        existing_type=postgresql.JSONB(astext_type=sa.Text()),
        type_=sa.Text(),
        existing_nullable=True,
        postgresql_using="CASE WHEN extra IS NULL THEN NULL ELSE extra::text END",
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not _extra_is_text(conn):
        return
    conn.execute(
        sa.text(
            """
            UPDATE margesi
            SET extra = NULL
            WHERE extra IS NOT NULL
              AND (TRIM(extra) = '' OR UPPER(TRIM(extra)) = 'NULL')
            """
        )
    )
    op.alter_column(
        "margesi",
        "extra",
        existing_type=sa.Text(),
        type_=postgresql.JSONB(astext_type=sa.Text()),
        existing_nullable=True,
        postgresql_using="""
            CASE
                WHEN extra IS NULL OR TRIM(extra) = '' THEN NULL
                ELSE extra::jsonb
            END
        """,
    )
