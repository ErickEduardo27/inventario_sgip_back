"""Helpers COPY → tabla temporal → upsert masivo PostgreSQL."""

from __future__ import annotations

import csv
import io
from typing import Any, Sequence

import pandas as pd


def ensure_staging_table(cur, *, table_name: str, columns_ddl: str) -> None:
    """Crea staging TEMP una sola vez por conexión (aislada entre workers Celery)."""
    cur.execute(
        f"""
        CREATE TEMP TABLE IF NOT EXISTS {table_name} (
            {columns_ddl}
        ) ON COMMIT DROP
        """
    )


def truncate_staging(cur, table_name: str) -> None:
    cur.execute(f"TRUNCATE {table_name}")


def copy_csv_to_temp(
    cur,
    *,
    table_name: str,
    table_ddl: str,
    columns: Sequence[str],
    rows: list[list[Any]],
) -> None:
    # Misma transacción + varios chunks: la temp no desaparece hasta COMMIT.
    cur.execute(f"DROP TABLE IF EXISTS {table_name}")
    cur.execute(table_ddl)
    if not rows:
        return
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for row in rows:
        writer.writerow(row)
    buf.seek(0)
    cols_sql = ", ".join(columns)
    cur.copy_expert(
        f"COPY {table_name} ({cols_sql}) FROM STDIN WITH (FORMAT CSV)",
        buf,
    )


def copy_dataframe_csv(
    cur,
    *,
    table_name: str,
    columns: Sequence[str],
    df: pd.DataFrame,
) -> None:
    if df.empty:
        return
    buf = io.StringIO()
    df.loc[:, list(columns)].to_csv(
        buf,
        index=False,
        header=False,
        quoting=csv.QUOTE_MINIMAL,
        lineterminator="\n",
    )
    buf.seek(0)
    cols_sql = ", ".join(columns)
    cur.copy_expert(
        f"COPY {table_name} ({cols_sql}) FROM STDIN WITH (FORMAT CSV)",
        buf,
    )


def csv_cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value)
