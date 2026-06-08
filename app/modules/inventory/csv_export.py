"""Exportación masiva CSV vía PostgreSQL COPY (rápida para cientos de miles de filas)."""

from __future__ import annotations

import io
from datetime import date
from uuid import UUID

from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.session import engine


def copy_query_to_csv_bytes(inner_sql: str, params: tuple) -> bytes:
    """Ejecuta ``COPY (SELECT …) TO STDOUT WITH CSV HEADER`` sobre conexión DBAPI directa."""
    conn = engine.raw_connection()
    try:
        cur = conn.cursor()
        copy_sql = cur.mogrify(
            "COPY (" + inner_sql + ") TO STDOUT WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')",
            params,
        ).decode("utf-8")
        buf = io.BytesIO()
        cur.copy_expert(copy_sql, buf)
        return buf.getvalue()
    finally:
        conn.rollback()
        conn.close()


def csv_download_response(
    db: Session,
    *,
    tenant_id: UUID,
    inner_sql: str,
    filename_base: str,
) -> Response:
    """Genera respuesta HTTP con CSV UTF-8 (BOM opcional para Excel en Windows)."""
    _ = db  # reservado por compatibilidad con Depends(get_db)
    payload = copy_query_to_csv_bytes(inner_sql, (str(tenant_id),))
    stamp = date.today().isoformat()
    filename = f"{filename_base}_{stamp}.csv"
    return Response(
        content=b"\xef\xbb\xbf" + payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
