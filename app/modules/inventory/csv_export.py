"""Exportación masiva CSV vía PostgreSQL COPY (rápida para cientos de miles de filas)."""

import io
import logging
from datetime import date
from typing import Any
from uuid import UUID

from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.db.session import engine

logger = logging.getLogger(__name__)

def copy_query_to_csv_bytes(inner_sql: str, params: tuple) -> bytes:
    """Ejecuta COPY (SELECT …) TO STDOUT WITH CSV HEADER."""
    conn = engine.raw_connection()

    try:
        cur = conn.cursor()

        copy_sql = cur.mogrify(
            "COPY (" + inner_sql + ") TO STDOUT WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')",
            params,
        ).decode("utf-8")

        buf = io.BytesIO()

        logger.info("INICIO EXPORT")

        cur.copy_expert(copy_sql, buf)

        logger.info("COPY FINALIZADO")

        payload = buf.getvalue()

        logger.info(
            "CSV SIZE %.2f MB",
            len(payload) / 1024 / 1024
        )

        return payload

    except Exception:
        logger.exception("ERROR DURANTE COPY")
        raise

    finally:
        conn.rollback()
        conn.close()


def csv_download_response(
    db: Session,
    *,
    tenant_id: UUID,
    inner_sql: str,
    filename_base: str,
    params: tuple[Any, ...] | None = None,
) -> Response:
    """Genera respuesta HTTP con CSV UTF-8 (BOM opcional para Excel en Windows)."""
    _ = db  # reservado por compatibilidad con Depends(get_db)
    bind_params = params if params is not None else (str(tenant_id),)
    payload = copy_query_to_csv_bytes(inner_sql, bind_params)
    stamp = date.today().isoformat()
    filename = f"{filename_base}_{stamp}.csv"
    return Response(
        content=b"\xef\xbb\xbf" + payload,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
