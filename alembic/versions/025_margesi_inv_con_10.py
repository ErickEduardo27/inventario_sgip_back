"""``margesi.inv_con``: VARCHAR(10)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "025_margesi_inv_con_10"
down_revision = "024_cc_description_70"
branch_labels = None
depends_on = None


def _inv_con_max_len(conn: sa.Connection) -> int | None:
    row = conn.execute(
        sa.text(
            """
            SELECT character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'margesi'
              AND column_name = 'inv_con'
            """
        )
    ).first()
    if not row or row[0] is None:
        return None
    return int(row[0])


def upgrade() -> None:
    conn = op.get_bind()
    current = _inv_con_max_len(conn)
    if current is not None and current >= 10:
        return
    op.alter_column(
        "margesi",
        "inv_con",
        existing_type=sa.String(length=current or 2),
        type_=sa.String(length=10),
        existing_nullable=True,
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            UPDATE margesi
            SET inv_con = LEFT(inv_con, 2)
            WHERE inv_con IS NOT NULL AND char_length(inv_con) > 2
            """
        )
    )
    op.alter_column(
        "margesi",
        "inv_con",
        existing_type=sa.String(length=10),
        type_=sa.String(length=2),
        existing_nullable=True,
    )
