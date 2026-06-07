"""Expande ``margesi`` a columnas físicas (Laravel Item). Migra datos desde ``extra`` JSONB.

Idempotente: tolera ejecución parcial previa (columnas/índices ya creados en producción).
"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "023_margesi_full"
down_revision = "022_cc_principal_fk"
branch_labels = None
depends_on = None

_SKIP_STRING = frozenset({"mar_cpat", "mar_des", "inv_sit", "inv_con", "inv_num", "inv_hoj"})


def _margesi_columns(conn: sa.Connection) -> set[str]:
    rows = conn.execute(
        sa.text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'margesi'
            """
        )
    ).scalars()
    return set(rows)


def _column_char_max(conn: sa.Connection, column: str) -> int | None:
    row = conn.execute(
        sa.text(
            """
            SELECT character_maximum_length
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'margesi'
              AND column_name = :col
            """
        ),
        {"col": column},
    ).first()
    if not row or row[0] is None:
        return None
    return int(row[0])


def _constraint_exists(conn: sa.Connection, name: str) -> bool:
    return (
        conn.execute(
            sa.text("SELECT 1 FROM pg_constraint WHERE conname = :n"),
            {"n": name},
        ).first()
        is not None
    )


def _index_exists(conn: sa.Connection, name: str) -> bool:
    return (
        conn.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE schemaname = current_schema() AND indexname = :n"),
            {"n": name},
        ).first()
        is not None
    )


def _add_column_if_missing(existing: set[str], name: str, column: sa.Column) -> None:
    if name not in existing:
        op.add_column("margesi", column)


def _widen_varchar(conn: sa.Connection, existing: set[str], name: str, width: int) -> None:
    if name not in existing:
        return
    current = _column_char_max(conn, name)
    if current is not None and current < width:
        op.alter_column("margesi", name, type_=sa.String(length=width), existing_nullable=True)


def upgrade() -> None:
    from app.modules.inventory.margesi_fields import (
        EXTRA_KEY_TO_COLUMN,
        MARGESI_DATE_COLS,
        MARGESI_DECIMAL_COLS,
        MARGESI_ENUM_COLS,
        MARGESI_INT_COLS,
        MARGESI_STRING_COLS,
        MARGESI_STRING_MAX,
        all_margesi_column_names,
    )
    from app.modules.inventory.margesi_mapper import coerce_column_value

    def _fit(col: str, val: Any) -> Any:
        coerced = coerce_column_value(col, val, excel_date=(col == "mar_cont_fec"))
        if coerced is None:
            return None
        if isinstance(coerced, str):
            max_len = MARGESI_STRING_MAX.get(col)
            if max_len and len(coerced) > max_len:
                return coerced[:max_len]
        return coerced

    conn = op.get_bind()
    existing = _margesi_columns(conn)

    for name, length in MARGESI_STRING_COLS:
        if name in _SKIP_STRING:
            continue
        ln = length or 255
        _add_column_if_missing(existing, name, sa.Column(name, sa.String(length=ln), nullable=True))
        existing.add(name)
        _widen_varchar(conn, existing, name, ln)

    for name, _vals, default in MARGESI_ENUM_COLS:
        _add_column_if_missing(
            existing,
            name,
            sa.Column(name, sa.String(length=1), nullable=True, server_default=default),
        )
        existing.add(name)

    for name in MARGESI_INT_COLS:
        if name in ("inv_num", "inv_hoj"):
            continue
        _add_column_if_missing(existing, name, sa.Column(name, sa.BigInteger(), nullable=True))
        existing.add(name)

    for name in MARGESI_DATE_COLS:
        _add_column_if_missing(existing, name, sa.Column(name, sa.Date(), nullable=True))
        existing.add(name)

    for name in MARGESI_DECIMAL_COLS:
        _add_column_if_missing(existing, name, sa.Column(name, sa.Numeric(16, 2), nullable=True))
        existing.add(name)

    for col, width in (
        ("mar_cpat", 20),
        ("mar_des", 120),
        ("inv_sit", 15),
        ("inv_con", 10),
    ):
        _widen_varchar(conn, existing, col, width)

    all_cols = set(all_margesi_column_names())
    rows = conn.execute(sa.text("SELECT id, extra FROM margesi WHERE extra IS NOT NULL")).mappings().all()

    for row in rows:
        ex_raw = row["extra"]
        if isinstance(ex_raw, str):
            try:
                ex: dict[str, Any] = json.loads(ex_raw)
            except json.JSONDecodeError:
                continue
        elif isinstance(ex_raw, dict):
            ex = dict(ex_raw)
        else:
            continue

        conta = ex.pop("contabilidad", None)
        if isinstance(conta, dict):
            ex.update({k: v for k, v in conta.items() if v is not None})

        sets: dict[str, Any] = {}
        leftover: dict[str, Any] = {}
        for key, val in ex.items():
            if key in ("list_sbn_id", "cat_ultimo", "flag_etiquetado", "flag_depreciacion"):
                leftover[key] = val
                continue
            col = EXTRA_KEY_TO_COLUMN.get(key, key if key in all_cols else None)
            if not col:
                leftover[key] = val
                continue
            if col not in existing:
                leftover[key] = val
                continue
            if val is None or (isinstance(val, str) and not str(val).strip()):
                continue
            coerced = _fit(col, val)
            if coerced is not None:
                sets[col] = coerced

        if not sets and not leftover:
            continue

        extra_val = leftover or None
        if sets:
            assignments = ", ".join(f'"{k}" = :{k}' for k in sets)
            conn.execute(sa.text(f"UPDATE margesi SET {assignments} WHERE id = :id"), {"id": row["id"], **sets})
        if extra_val is None:
            conn.execute(sa.text("UPDATE margesi SET extra = NULL WHERE id = :id"), {"id": row["id"]})
        else:
            conn.execute(
                sa.text("UPDATE margesi SET extra = CAST(:extra AS jsonb) WHERE id = :id"),
                {"id": row["id"], "extra": json.dumps(extra_val)},
            )

    conn.execute(
        sa.text(
            """
            UPDATE margesi
            SET mar_num = COALESCE(
                NULLIF(TRIM(mar_num), ''),
                NULLIF(TRIM(extra->>'mar_num'), ''),
                NULLIF(TRIM(extra->>'codigo_interno'), '')
            )
            WHERE (mar_num IS NULL OR TRIM(mar_num) = '')
              AND extra IS NOT NULL
            """
        )
    )

    for en, _vals, default in MARGESI_ENUM_COLS:
        conn.execute(
            sa.text(f"UPDATE margesi SET {en} = :d WHERE {en} IS NULL OR TRIM({en}) = ''"),
            {"d": default},
        )
        op.alter_column("margesi", en, nullable=False, server_default=default)

    if not _constraint_exists(conn, "ck_margesi_mar_est"):
        op.create_check_constraint("ck_margesi_mar_est", "margesi", "mar_est IN ('N','B','R','M','I')")
    if not _constraint_exists(conn, "ck_margesi_mar_uso"):
        op.create_check_constraint("ck_margesi_mar_uso", "margesi", "mar_uso IN ('S','N')")
    if not _constraint_exists(conn, "ck_margesi_mar_seg"):
        op.create_check_constraint("ck_margesi_mar_seg", "margesi", "mar_seg IN ('S','N')")

    if not _index_exists(conn, "ix_margesi_mar_num"):
        op.create_index("ix_margesi_mar_num", "margesi", ["mar_num"])


def downgrade() -> None:
    from app.modules.inventory.margesi_fields import (
        MARGESI_DATE_COLS,
        MARGESI_DECIMAL_COLS,
        MARGESI_ENUM_COLS,
        MARGESI_INT_COLS,
        MARGESI_STRING_COLS,
    )

    conn = op.get_bind()
    if _index_exists(conn, "ix_margesi_mar_num"):
        op.drop_index("ix_margesi_mar_num", table_name="margesi")
    for name in ("ck_margesi_mar_est", "ck_margesi_mar_uso", "ck_margesi_mar_seg"):
        if _constraint_exists(conn, name):
            op.drop_constraint(name, "margesi", type_="check")

    existing = _margesi_columns(conn)
    skip = _SKIP_STRING | {"extra"}
    for name, _ in MARGESI_STRING_COLS:
        if name not in skip and name in existing:
            op.drop_column("margesi", name)
    for name, _v, _d in MARGESI_ENUM_COLS:
        if name in existing:
            op.drop_column("margesi", name)
    for name in MARGESI_INT_COLS:
        if name not in ("inv_num", "inv_hoj") and name in existing:
            op.drop_column("margesi", name)
    for name in MARGESI_DATE_COLS:
        if name in existing:
            op.drop_column("margesi", name)
    for name in MARGESI_DECIMAL_COLS:
        if name in existing:
            op.drop_column("margesi", name)

    op.alter_column("margesi", "mar_cpat", type_=sa.String(length=200), existing_nullable=True)
    op.alter_column("margesi", "mar_des", type_=sa.String(length=500), existing_nullable=True)
    op.alter_column("margesi", "inv_sit", type_=sa.String(length=50), existing_nullable=True)
    op.alter_column("margesi", "inv_con", type_=sa.String(length=50), existing_nullable=True)
