"""``COPY … TO STDOUT`` compatible con psycopg2 y psycopg 3.

El proyecto corre con ambos drivers según ``DATABASE_URL`` (``postgresql+psycopg2://`` en desarrollo,
``postgresql+psycopg://`` en producción). psycopg 3 no tiene ``cursor.mogrify`` ni ``copy_expert``: usa
``ClientCursor.mogrify`` y ``cursor.copy()``.
"""

from __future__ import annotations

from typing import Any, Protocol


class _Writable(Protocol):
    def write(self, data: bytes) -> Any: ...


def _driver_connection(raw_conn):
    """Conexión DBAPI real detrás del proxy de pool de SQLAlchemy."""
    return getattr(raw_conn, "driver_connection", None) or getattr(raw_conn, "dbapi_connection", None) or raw_conn


def render_sql(raw_conn, sql: str, params: tuple | list | None) -> str:
    """SQL con los parámetros incrustados (lado cliente), igual que ``mogrify`` de psycopg2."""
    cur = raw_conn.cursor()
    try:
        if hasattr(cur, "mogrify"):  # psycopg2
            out = cur.mogrify(sql, params)
            return out.decode("utf-8") if isinstance(out, (bytes, bytearray)) else out
    finally:
        cur.close()
    import psycopg  # psycopg 3

    return psycopg.ClientCursor(_driver_connection(raw_conn)).mogrify(sql, params)


def copy_to(raw_conn, copy_sql: str, dest: _Writable) -> None:
    """Ejecuta ``COPY (...) TO STDOUT`` (ya renderizado) y escribe los bytes en ``dest``."""
    cur = raw_conn.cursor()
    try:
        if hasattr(cur, "copy_expert"):  # psycopg2
            cur.copy_expert(copy_sql, dest)
            return
        with cur.copy(copy_sql) as copy:  # psycopg 3
            for chunk in copy:
                dest.write(bytes(chunk))
    finally:
        cur.close()
