"""interior_photos en establishments: hasta 4 fotos de ambientes internos del local.

La fachada sigue en ``photo_blob``/``photo_token``; las internas se guardan como rutas
públicas (GCS o disco) generadas por ``public_photo_storage`` (kind ``establishment``).

Revision ID: 054_establishment_photos
Revises: 053_descarga_request_key
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "054_establishment_photos"
down_revision = "053_descarga_request_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("establishments", sa.Column("interior_photos", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("establishments", "interior_photos")
