"""CC principal: FK de cost_center.principal_center_id hacia cost_center (no establishments).

Revision ID: 022_cc_principal_fk
Revises: 021_geo_catalog_fk
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "022_cc_principal_fk"
down_revision = "021_geo_catalog_fk"
branch_labels = None
depends_on = None

_NEW_FK = "fk_cost_center_principal_center_id"


def _drop_principal_center_fks(conn: sa.Connection) -> None:
    """Elimina cualquier FK sobre cost_center.principal_center_id (nombre varía por entorno)."""
    rows = conn.execute(
        sa.text(
            """
            SELECT tc.constraint_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_schema = kcu.constraint_schema
             AND tc.constraint_name = kcu.constraint_name
            WHERE tc.constraint_schema = current_schema()
              AND tc.table_name = 'cost_center'
              AND tc.constraint_type = 'FOREIGN KEY'
              AND kcu.column_name = 'principal_center_id'
            """
        )
    ).fetchall()
    for (name,) in rows:
        conn.execute(sa.text(f'ALTER TABLE cost_center DROP CONSTRAINT IF EXISTS "{name}"'))

    for legacy in (
        "cost_center_principal_center_id_fkey",
        _NEW_FK,
    ):
        conn.execute(sa.text(f'ALTER TABLE cost_center DROP CONSTRAINT IF EXISTS "{legacy}"'))


def _principal_fk_exists(conn: sa.Connection, name: str) -> bool:
    return (
        conn.execute(
            sa.text(
                """
                SELECT 1
                FROM information_schema.table_constraints
                WHERE constraint_schema = current_schema()
                  AND table_name = 'cost_center'
                  AND constraint_name = :name
                  AND constraint_type = 'FOREIGN KEY'
                """
            ),
            {"name": name},
        ).fetchone()
        is not None
    )


def upgrade() -> None:
    conn = op.get_bind()
    op.execute(
        """
        UPDATE cost_center
        SET principal_center_id = NULL
        WHERE principal_center_id IS NOT NULL
          AND principal_center_id NOT IN (SELECT id FROM cost_center)
        """
    )
    _drop_principal_center_fks(conn)
    if not _principal_fk_exists(conn, _NEW_FK):
        op.create_foreign_key(
            _NEW_FK,
            "cost_center",
            "cost_center",
            ["principal_center_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    conn = op.get_bind()
    _drop_principal_center_fks(conn)
    op.execute("UPDATE cost_center SET principal_center_id = NULL WHERE principal_center_id IS NOT NULL")
    if not _principal_fk_exists(conn, "cost_center_principal_center_id_fkey"):
        op.create_foreign_key(
            "cost_center_principal_center_id_fkey",
            "cost_center",
            "establishments",
            ["principal_center_id"],
            ["id"],
            ondelete="SET NULL",
        )
