"""Centro de costo: ``description`` VARCHAR(70) (Laravel CostoCentro)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "024_cc_description_70"
down_revision = "023_margesi_full"
branch_labels = None
depends_on = None


def _description_max_len(conn: sa.Connection) -> int | None:
    row = conn.execute(
        sa.text(
            """
            SELECT character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'cost_center'
              AND column_name = 'description'
            """
        )
    ).first()
    if not row or row[0] is None:
        return None
    return int(row[0])


def upgrade() -> None:
    conn = op.get_bind()
    current = _description_max_len(conn)
    if current is not None and current <= 70:
        return

    conn.execute(
        sa.text(
            """
            UPDATE cost_center
            SET description = LEFT(description, 70)
            WHERE char_length(description) > 70
            """
        )
    )
    op.alter_column(
        "cost_center",
        "description",
        existing_type=sa.String(length=current or 500),
        type_=sa.String(length=70),
        existing_nullable=False,
    )


def downgrade() -> None:
    conn = op.get_bind()
    current = _description_max_len(conn)
    if current is None or current > 70:
        return
    op.alter_column(
        "cost_center",
        "description",
        existing_type=sa.String(length=70),
        type_=sa.String(length=500),
        existing_nullable=False,
    )
