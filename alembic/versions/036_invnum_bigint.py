"""hoj_num e inv_num numéricos (BIGINT) y únicos por tenant.

Revision ID: 036_invnum_bigint
Revises: 035_reporte_aptot_module
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "036_invnum_bigint"
down_revision = "035_reporte_aptot_module"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_cards_tenant_hoj_num")
    op.execute("DROP INDEX IF EXISTS ix_cards_hoj_num")
    op.execute("DROP INDEX IF EXISTS ix_itemcards_inv_num")

    # Normalizar hoj_num → dígitos; vacíos → 0
    op.execute(
        """
        UPDATE cards
        SET hoj_num = COALESCE(NULLIF(regexp_replace(trim(hoj_num), '[^0-9]', '', 'g'), ''), '0')
        """
    )

    # Eliminar duplicados de hoj_num por tenant (conservar menor id)
    op.execute(
        """
        DELETE FROM cards a
        USING cards b
        WHERE a.tenant_id = b.tenant_id
          AND NULLIF(regexp_replace(trim(a.hoj_num), '[^0-9]', '', 'g'), '')::bigint
            = NULLIF(regexp_replace(trim(b.hoj_num), '[^0-9]', '', 'g'), '')::bigint
          AND a.id > b.id
        """
    )

    # Quitar default '' (VARCHAR) antes del cast; PostgreSQL no lo convierte a BIGINT
    op.execute("ALTER TABLE cards ALTER COLUMN hoj_num DROP DEFAULT")

    op.execute(
        """
        ALTER TABLE cards
        ALTER COLUMN hoj_num TYPE BIGINT
        USING COALESCE(
            NULLIF(regexp_replace(trim(hoj_num::text), '[^0-9]', '', 'g'), '')::bigint,
            0
        )
        """
    )
    op.alter_column("cards", "hoj_num", nullable=False, server_default="0")

    # inv_num: vacíos → id (garantiza valor único temporal antes del cast)
    op.execute(
        """
        UPDATE itemcards
        SET inv_num = id::text
        WHERE inv_num IS NULL OR trim(inv_num) = '' OR inv_num !~ '^[0-9]+$'
        """
    )

    op.execute(
        """
        DELETE FROM itemcards a
        USING itemcards b
        WHERE a.tenant_id = b.tenant_id
          AND a.inv_num = b.inv_num
          AND a.id > b.id
        """
    )

    op.execute(
        """
        ALTER TABLE itemcards
        ALTER COLUMN inv_num TYPE BIGINT
        USING NULLIF(regexp_replace(trim(inv_num), '[^0-9]', '', 'g'), '')::bigint
        """
    )
    op.alter_column("itemcards", "inv_num", nullable=False)

    op.create_unique_constraint("uq_cards_tenant_hoj_num", "cards", ["tenant_id", "hoj_num"])
    op.create_unique_constraint("uq_itemcards_tenant_inv_num", "itemcards", ["tenant_id", "inv_num"])


def downgrade() -> None:
    op.drop_constraint("uq_itemcards_tenant_inv_num", "itemcards", type_="unique")
    op.drop_constraint("uq_cards_tenant_hoj_num", "cards", type_="unique")

    op.execute(
        """
        ALTER TABLE cards
        ALTER COLUMN hoj_num TYPE VARCHAR(50)
        USING lpad(hoj_num::text, 5, '0')
        """
    )
    op.alter_column("cards", "hoj_num", server_default="")
    op.execute(
        """
        ALTER TABLE itemcards
        ALTER COLUMN inv_num TYPE VARCHAR(100)
        USING inv_num::text
        """
    )
    op.alter_column("itemcards", "inv_num", nullable=True)

    op.create_index("ix_cards_hoj_num", "cards", ["hoj_num"])
    op.create_index("ix_itemcards_inv_num", "itemcards", ["inv_num"])
    op.execute(
        """
        CREATE UNIQUE INDEX uq_cards_tenant_hoj_num
        ON cards (tenant_id, hoj_num)
        """
    )
